"""Resolve, probe and rank several embeds of the same episode.

The auto source picker needs to answer three questions before handing a link
to a player: does it still resolve, what kind of stream is it (HLS master,
HLS media or a progressive file) and how good is it. Resolution is done by
the regular extractors; probing reuses the same impersonated HTTP stack so a
host protected by a bot check is judged the same way the proxy will serve it.

Everything below the ``fetch`` seam is pure and unit tested: the network is
injected, never mocked at the module level.
"""

from __future__ import annotations

import re
import struct
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from . import player
from ..proxy import DNS_OPTIONS

# Stream kinds. A dead link is a kind too, so a probe result and a probe
# failure share a single shape all the way up to the menu.
KIND_HLS_MASTER = "hls_master"
KIND_HLS_MEDIA = "hls_media"
KIND_MP4 = "mp4"
KIND_DEAD = "dead"

KIND_LABELS = {
    KIND_HLS_MASTER: "HLS",
    KIND_HLS_MEDIA: "HLS",
    KIND_MP4: "MP4",
    KIND_DEAD: "dead",
}

# A probe that outlives this is worthless: the user is waiting on a menu.
DEFAULT_TIMEOUT = 8.0

# Consecutive embeds are resolved in parallel. A dozen workers would only
# queue requests behind the same CDN rate limiter.
DEFAULT_MAX_WORKERS = 6

# A link older than this is re-extracted before being handed to the player,
# because the tokens behind most CDN URLs do not outlive the wait.
STALE_AFTER = 120.0

# EXT-X-STREAM-INF carries the variant attributes; RESOLUTION and BANDWIDTH
# are what "quality" means for an HLS source.
_VARIANT_RE = re.compile(r"#EXT-X-STREAM-INF:([^\r\n]*)")
_ATTR_RE = re.compile(r'([A-Z0-9-]+)=("[^"]*"|[^,]*)')


def _variant_attrs(line: str) -> dict:
    """Parse the attribute list of an EXT-X-STREAM-INF line."""
    attrs = {}
    for key, value in _ATTR_RE.findall(line):
        attrs[key] = value.strip('"')
    return attrs


def parse_master_qualities(text: str) -> list[tuple]:
    """Extract ``(height, bandwidth)`` for every variant of a master playlist.

    Returns an empty list for a media playlist (a single rendition, no
    variant to choose from) or for anything that is not a playlist.
    Entries are sorted best first.
    """
    if not text or "#EXTM3U" not in text[:512]:
        return []

    qualities = []
    for attrs in _VARIANT_RE.findall(text):
        parsed = _variant_attrs(attrs)

        height = 0
        resolution = parsed.get("RESOLUTION", "")
        if "x" in resolution:
            try:
                height = int(resolution.split("x")[-1])
            except ValueError:
                height = 0

        try:
            bandwidth = int(parsed.get("BANDWIDTH") or 0)
        except ValueError:
            bandwidth = 0

        # A variant with neither signal would rank as a broken entry; skip it
        # rather than let it tie with a dead link at the bottom of the list.
        if height or bandwidth:
            qualities.append((height, bandwidth))

    qualities.sort(key=lambda q: (q[0], q[1]), reverse=True)
    return qualities


def guess_kind(stream_url: str, player_config: dict = None) -> str:
    """Classify a resolved URL without touching the network.

    The embed config is the most reliable hint (``ext: "mp4"`` is set by hand
    for every progressive embed); the URL path is the fallback for a link that
    went through a redirector.
    """
    config = player_config or {}
    if config.get("ext") == "mp4":
        return KIND_MP4

    path = urllib.parse.urlparse(stream_url).path.lower()
    if path.endswith((".m3u8", ".m3u")):
        return KIND_HLS_MASTER
    if path.endswith((".mp4", ".webm", ".m4v", ".mov", ".mkv", ".avi")):
        return KIND_MP4
    return KIND_HLS_MASTER


def _mp4_height(head: bytes) -> int | None:
    """Best-effort track height from the ``tkhd`` box in an MP4 header chunk.

    ``tkhd`` stores the display size as 16.16 fixed point. It is usually in
    the first boxes, but never guaranteed (a file without a faststart start
    puts ``moov`` at the end), so this returns ``None`` rather than guessing
    when the box is absent or the values are not plausible for a video track.
    """
    for match in re.finditer(b"tkhd", head):
        # Layout after the 4-byte box type: version+flags (4), creation and
        # modification times (8), track id (4), reserved (4), duration (4),
        # reserved (8), layer / alternate group / volume / reserved (8),
        # matrix (36). Width and height are 16.16 fixed point.
        offset = match.end() + 4 + 8 + 4 + 4 + 4 + 8 + 8 + 36
        if offset + 8 > len(head):
            continue
        width, height = struct.unpack(">II", head[offset : offset + 8])
        width >>= 16
        height >>= 16
        if 0 < height < 4000 and height < width < 20000:
            return height
    return None


def _content_total(headers: dict) -> int:
    """Total object size from Content-Length or a Range answer (206)."""
    headers = {k.lower(): v for k, v in (headers or {}).items()}
    length = headers.get("content-length")
    if length and length.isdigit():
        return int(length)
    content_range = headers.get("content-range", "")
    match = re.search(r"/(\d+)\s*$", content_range)
    return int(match.group(1)) if match else 0


@dataclass
class ProbeResponse:
    """Minimal response shape, so tests can build one without curl_cffi."""

    status: int
    headers: dict = field(default_factory=dict)
    content: bytes = b""

    @property
    def text(self) -> str:
        return self.content.decode("utf-8", errors="replace")


def _default_fetch(
    url: str, headers: dict, *, range_bytes: bool = False, timeout: float = DEFAULT_TIMEOUT
) -> ProbeResponse:
    """Fetch a stream with the same impersonated stack the proxy uses."""
    from curl_cffi import requests

    request_headers = dict(headers or {})
    request_headers.setdefault(
        "User-Agent",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    )
    if range_bytes:
        # Just enough to read the MP4 header box, while a range-capable host
        # answers with 206 instead of streaming a whole episode.
        request_headers["Range"] = "bytes=0-65535"

    session = requests.Session(curl_options=DNS_OPTIONS, allow_redirects="safe")
    try:
        response = session.get(
            url, headers=request_headers, impersonate="chrome", timeout=timeout
        )
    finally:
        session.close()

    return ProbeResponse(
        status=response.status_code,
        headers=dict(response.headers),
        content=response.content,
    )


def _looks_blocked(response: ProbeResponse) -> bool:
    """True when the body is a bot-check page rather than a stream."""
    head = response.content[:256].lstrip().lower()
    if not head:
        return True
    return head.startswith((b"<html", b"<!doctype", b"<script", b"<head", b"<body"))


def probe_stream(
    stream_url: str,
    headers: dict,
    player_config: dict = None,
    fetch=None,
    timeout: float = DEFAULT_TIMEOUT,
) -> dict:
    """Check a resolved link and report its kind, size and available heights.

    Returns a dict with ``ok``, ``kind``, ``heights`` and ``size``. A link that
    answers 403, times out or serves a challenge page is reported as not ok
    rather than raised, so one dead embed never hides the others.
    """
    fetch = fetch or _default_fetch
    kind = guess_kind(stream_url, player_config)
    result = {"ok": False, "kind": KIND_DEAD, "heights": [], "bandwidths": [], "size": 0}

    try:
        response = fetch(
            stream_url, headers, range_bytes=(kind == KIND_MP4), timeout=timeout
        )
    except Exception as e:
        result["error"] = f"{type(e).__name__}: {e}"
        return result

    if response.status not in (200, 206):
        result["error"] = f"HTTP {response.status}"
        return result

    if kind == KIND_MP4:
        # A CDN can answer a .mp4 URL with a playlist (and the reverse); the
        # body decides, not the URL.
        if b"#EXTM3U" in response.content[:512]:
            kind = KIND_HLS_MASTER
        else:
            if _looks_blocked(response):
                result["error"] = "blocked"
                return result
            height = _mp4_height(response.content)
            result.update(
                ok=True,
                kind=KIND_MP4,
                heights=[height] if height else [],
                size=_content_total(response.headers),
            )
            return result

    if _looks_blocked(response):
        result["error"] = "blocked"
        return result

    qualities = parse_master_qualities(response.text)
    result.update(
        ok=True,
        kind=KIND_HLS_MASTER if qualities else KIND_HLS_MEDIA,
        heights=[q[0] for q in qualities if q[0]],
        bandwidths=[q[1] for q in qualities if q[1]],
    )
    return result


def embed_host_label(url: str) -> str:
    """Short host label of a source URL ("https://sibnet.ru/e" -> "sibnet").

    Same label the source menu has always shown next to the provider name;
    kept here so both menus format a source the same way.
    """
    parts = (url or "").split("/")
    host = parts[2] if len(parts) > 2 else ""
    labels = host.split(".")
    return labels[-2] if len(labels) > 1 else host


@dataclass
class ResolvedSource:
    """One embed taken all the way to a playable link.

    The stream URL is meaningless without the headers and the embed config it
    was extracted with: that is why they travel together instead of being
    re-derived from the episode later.
    """

    embed_name: str
    embed_url: str
    headers: dict
    player_config: dict
    stream_url: str = None
    subtitle_url: str = None
    kind: str = KIND_DEAD
    heights: list = field(default_factory=list)
    bandwidths: list = field(default_factory=list)
    size: int = 0
    ok: bool = False
    error: str = None
    elapsed: float = 0.0
    probed_at: float = 0.0

    @property
    def is_stale(self) -> bool:
        """True when the link sat long enough in the menu to have expired.

        Tokenized CDN links are often only valid for a few minutes, so a
        source the user deliberated over may no longer resolve at launch.
        """
        return (time.monotonic() - self.probed_at) > STALE_AFTER

    @property
    def best_height(self) -> int:
        return max(self.heights) if self.heights else 0

    @property
    def best_bandwidth(self) -> int:
        return max(self.bandwidths) if self.bandwidths else 0

    @property
    def quality_label(self) -> str:
        """Short human label of what this source offers."""
        if self.best_height:
            return f"{self.best_height}p"
        if self.kind == KIND_HLS_MEDIA:
            return "HLS"
        if self.kind == KIND_MP4 and self.size:
            return f"~{self.size / (1024 * 1024):.0f} MB"
        return "?"

    @property
    def type_label(self) -> str:
        return KIND_LABELS.get(self.kind, self.kind)

    def menu_label(self) -> str:
        """One line for the source picker: name, then quality and origin.

        The name is formatted like the source list has always shown it
        ("Lecteur 2 : ansembed"), so both menus read the same way.
        """
        label = self.embed_name
        host = embed_host_label(self.embed_url)
        # The host is only worth showing when it says something the name does
        # not ("Lecteur 2 : ansembed", not "uqload : uqload").
        if host and host != self.embed_name:
            label = f"{label} : {host}"
        return (
            f"{label} · {self.quality_label}"
            f" · {self.type_label} · {self.elapsed:.1f}s"
        )


def _resolve_one(embed_name: str, embed_url: str, headers: dict, timeout: float,
                  fetch) -> ResolvedSource:
    """Resolve then probe a single embed, never raising."""
    config, _ = player.match_player_config(embed_url)
    source = ResolvedSource(
        embed_name=embed_name,
        embed_url=embed_url,
        headers=dict(headers or {}),
        player_config=config,
    )

    started = time.monotonic()
    try:
        stream_url, subtitle_url = player.get_hls_link(
            embed_url, dict(headers or {}), return_subs=True
        )
    except Exception as e:
        source.error = f"{type(e).__name__}: {e}"
        source.elapsed = time.monotonic() - started
        return source

    if not stream_url:
        source.error = "no stream found"
        source.elapsed = time.monotonic() - started
        return source

    if stream_url.startswith("/"):
        stream_url = (
            "https://"
            + embed_url.removeprefix("https://").removeprefix("http://").split("/")[0]
            + stream_url
        )

    source.stream_url = stream_url
    source.subtitle_url = subtitle_url

    probe = probe_stream(
        stream_url, source.headers, config, fetch=fetch, timeout=timeout
    )
    source.ok = probe["ok"]
    source.kind = probe["kind"]
    source.heights = probe["heights"]
    source.bandwidths = probe["bandwidths"]
    source.size = probe["size"]
    source.error = probe.get("error")
    source.elapsed = time.monotonic() - started
    source.probed_at = time.monotonic()
    return source


def resolve_source(embed_name: str, embed_url: str, headers: dict = None) -> ResolvedSource:
    """Resolve and probe a single embed (used to refresh a stale source)."""
    return _resolve_one(embed_name, embed_url, headers or {}, DEFAULT_TIMEOUT, None)


def rank_sources(sources: list[ResolvedSource]) -> list[ResolvedSource]:
    """Order working sources best first, dead ones last.

    Height is the primary signal because it is the only one a user actually
    compares. Bandwidth then file size break ties, so two HLS sources capped
    at 720p keep a stable and sensible order.
    """
    return sorted(
        sources,
        key=lambda s: (not s.ok, -s.best_height, -s.best_bandwidth, -s.size),
    )


def probe_sources(
    embeds: list,
    headers: dict = None,
    timeout: float = DEFAULT_TIMEOUT,
    max_workers: int = DEFAULT_MAX_WORKERS,
    fetch=None,
    on_start=None,
    on_done=None,
) -> list[ResolvedSource]:
    """Resolve and probe every embed in parallel, ranked best first.

    Args:
        embeds: Iterable of ``Player`` objects (name + embed URL).
        headers: Base headers of the episode, sent to every embed.
        timeout: Per-request timeout, in seconds, for each source.
        max_workers: Size of the resolution thread pool.
        fetch: Injected fetcher, for tests.
        on_start: Called with each embed name before it is resolved.
        on_done: Called with each source as soon as it finishes.

    Returns:
        The sources, ranked best first. Dead embeds are kept at the bottom so
        the menu can show why something was rejected instead of silently
        dropping it.
    """
    embeds = list(embeds)
    if not embeds:
        return []

    def work(embed):
        if on_start:
            on_start(embed.name)
        result = _resolve_one(embed.name, embed.url, headers or {}, timeout, fetch)
        if on_done:
            on_done(result)
        return result

    workers = max(1, min(max_workers, len(embeds)))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        # map preserves input order, so the source order does not depend on
        # which thread happened to finish first.
        return rank_sources(list(pool.map(work, embeds)))