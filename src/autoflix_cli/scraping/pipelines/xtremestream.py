"""xtremestream (ftk) playback pipeline.

The ftk webpack pipeline is provider-specific machinery behind a virtual
VOD playlist URL (/xs/master?data=...&u=...). It registers itself on the
shared proxy app through ``register`` (see proxy.register_pipelines), so
the proxy core stays free of provider protocol details.
"""
import hashlib
import json
import re
import threading
import urllib.parse

from Crypto.Cipher import AES
from Crypto.Util.Padding import unpad
from flask import Response, request

# Lazy attribute access on the shared proxy module: safe in both import
# orders (pipeline first or proxy first).
from ... import proxy as _proxy


# The web player (XSFTK in ftk_engine.js) no longer exposes a playlist URL:
# index.php boots with a signed token (``vt``) and everything happens through
# /player/proto_api.php:
#
#   op=manifest -> binary, XOR-filtered with sha256("M|<data>|<vt>"), decodes
#                  to {"<quality>": {durs, bw, res, td}, "audio": [...],
#                  "cdn": [host, ...]}
#   op=key      -> raw 16-byte AES-CBC key. Answers 403 "forbidden-hdr"
#                  without the X-XS-P: 1 header.
#
# Video segment i of a "<q>" variant (e.g. "720") lives on
# cdn[i % len(cdn)] at /cdn/down/<data>/<q>_enc/<q><i>.html and is encrypted
# with AES-CBC, IV = the segment index as 16-byte big-endian. The plaintext
# is a clear MPEG-TS carrying h264+aac. Audio segments are clear MPEG-TS
# (AAC only) served from /cdn/down/<data>/hls_audio/<lang>/seg_<i:03d>.aac.
# The sign/seg ops are pure telemetry: the CDN answers without them.
#
# The routes below materialize the playlists (/xs/master, /xs/media,
# /xs/audio) and decrypt every video segment (/xs/segment.ts) so mpv and
# hls.js just see a normal VOD HLS stream.
XS_BOOT_RE = re.compile(r'XSFTK\.boot\("[^"]+",\s*"([^"]+)"')

_xs_state: dict[str, dict] = {}  # data id -> {"url", "manifest", "token"}
_xs_state_lock = threading.Lock()
_xs_keys: dict[str, bytes] = {}  # data id -> AES-CBC key


class XsPipelineError(Exception):
    """The ftk bootstrap or segment pipeline failed for a data id."""


def _xs_xor_filter(payload: bytes, data_id: str, token: str) -> bytes:
    """Remove the manifest obfuscation (streaming XOR over a sha256 digest)."""
    digest = hashlib.sha256(f"M|{data_id}|{token}".encode()).digest()
    return bytes(b ^ digest[i % len(digest)] for i, b in enumerate(payload))


def _xs_origin(player_url: str) -> str:
    """Scheme + host of the player URL (index.php and proto_api share it)."""
    parts = urllib.parse.urlsplit(player_url)
    return f"{parts.scheme}://{parts.netloc}" if parts.netloc else player_url


def _xs_bootstrap(data_id: str, player_url: str) -> dict:
    """Fresh boot token + decoded manifest. Raises XsPipelineError."""
    resp = _proxy.fetch_with_retry(player_url, {"Referer": player_url})
    match = XS_BOOT_RE.search(resp.text) if resp and resp.status_code == 200 else None
    if not match:
        raise XsPipelineError("XSFTK boot token not found on the player page")

    token = match.group(1)
    api = f"{_xs_origin(player_url)}/player/proto_api.php"
    resp = _proxy.fetch_with_retry(
        f"{api}?data={data_id}&op=manifest&vt={token}", {"Referer": player_url}
    )
    if not resp or resp.status_code != 200:
        raise XsPipelineError("manifest fetch failed")
    try:
        manifest = json.loads(
            _xs_xor_filter(resp.content, data_id, token).decode("utf-8", "replace")
        )
    except ValueError as e:
        raise XsPipelineError(f"manifest decode failed: {e}") from e

    state = {"url": player_url, "manifest": manifest, "token": token}
    with _xs_state_lock:
        _xs_state[data_id] = state
    return state


def _xs_manifest(data_id: str, player_url: str, force: bool = False) -> dict:
    """Manifest for a data id, bootstrapped once per process (VOD: immutable)."""
    if not force:
        state = _xs_state.get(data_id)
        if state and state["url"] == player_url:
            return state["manifest"]
    return _xs_bootstrap(data_id, player_url)["manifest"]


def _xs_key(data_id: str, player_url: str, force: bool = False) -> bytes:
    """AES-CBC key, cached per data id (re-bootstraps the token when stale)."""
    if not force:
        key = _xs_keys.get(data_id)
        if key:
            return key
    state = _xs_bootstrap(data_id, player_url)
    api = f"{_xs_origin(player_url)}/player/proto_api.php"
    resp = _proxy.fetch_with_retry(
        f"{api}?data={data_id}&op=key&vt={state['token']}",
        {"Referer": player_url, "X-XS-P": "1"},
    )
    if not resp or resp.status_code != 200:
        raise XsPipelineError("key fetch failed")
    if len(resp.content) != AES.block_size:
        raise XsPipelineError("unexpected key size")
    _xs_keys[data_id] = resp.content
    return resp.content


def _xs_decrypt(raw: bytes, index: int, key: bytes) -> bytes:
    """AES-CBC decrypt with IV = the segment index (big-endian, 16 bytes)."""
    plain = AES.new(key, AES.MODE_CBC, iv=index.to_bytes(16, "big")).decrypt(raw)
    try:
        plain = unpad(plain, AES.block_size)
    except ValueError:
        pass
    if plain[:1] != b"\x47":
        raise ValueError("decryption did not produce MPEG-TS")
    return plain


def _xs_playlist_text(durs, target_duration, uri_for) -> str:
    """VOD media playlist body from the manifest durations."""
    lines = [
        "#EXTM3U",
        "#EXT-X-VERSION:3",
        f"#EXT-X-TARGETDURATION:{max(1, int(target_duration))}",
        "#EXT-X-MEDIA-SEQUENCE:0",
        "#EXT-X-PLAYLIST-TYPE:VOD",
    ]
    for i, dur in enumerate(durs):
        lines.append(f"#EXTINF:{dur!r},")
        lines.append(uri_for(i))
    lines.append("#EXT-X-ENDLIST")
    return "\n".join(lines) + "\n"


def _xs_playlist_response(text: str) -> Response:
    return Response(
        text,
        mimetype="application/vnd.apple.mpegurl",
        headers={"Access-Control-Allow-Origin": "*"},
    )


def _xs_variant_names(manifest: dict) -> list[str]:
    """Quality keys of the manifest, highest bandwidth first."""
    names = [
        k for k, v in manifest.items() if isinstance(v, dict) and "durs" in v
    ]

    def rank(name):
        return int(re.sub(r"\D", "", name) or 0)

    return sorted(names, key=rank, reverse=True)


def xs_master():
    data_id = request.args.get("data", "")
    player_url = request.args.get("u", "")
    if not data_id or not player_url:
        return "Missing data or player URL", 400

    try:
        manifest = _xs_manifest(data_id, player_url)
    except XsPipelineError as e:
        return f"xtremestream: {e}", 502

    base = f"http://{_proxy.PROXY_HOST}:{_proxy.PROXY_PORT}"
    quotes = urllib.parse.quote

    lines = ["#EXTM3U", "#EXT-X-VERSION:3"]
    audio_tracks = manifest.get("audio") or []
    for track in audio_tracks:
        lang = track.get("lang") or "und"
        name = track.get("name") or lang
        audio_uri = (
            f"{base}/xs/audio?data={quotes(data_id, safe='')}"
            f"&u={quotes(player_url, safe='')}&lang={quotes(lang, safe='')}"
        )
        lines.append(
            '#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="aud",'
            f'NAME="{name}",'
            + (f'LANGUAGE="{lang}",' if lang != "und" else "")
            + f'DEFAULT={"YES" if track.get("default") else "NO"},'
            "AUTOSELECT=YES,"
            f'URI="{audio_uri}"'
        )

    for name in _xs_variant_names(manifest):
        info = manifest[name]
        attrs = f"BANDWIDTH={int(info.get('bw') or 0)}"
        if info.get("res"):
            attrs += f",RESOLUTION={info['res']}"
        if audio_tracks:
            attrs += ',AUDIO="aud"'
        lines.append(f"#EXT-X-STREAM-INF:{attrs}")
        lines.append(
            f"{base}/xs/media?data={quotes(data_id, safe='')}"
            f"&u={quotes(player_url, safe='')}&q={quotes(name, safe='')}"
        )

    return _xs_playlist_response("\n".join(lines) + "\n")


def xs_media():
    data_id = request.args.get("data", "")
    player_url = request.args.get("u", "")
    quality = request.args.get("q", "")
    if not data_id or not player_url or not re.fullmatch(r"\d+p?", quality):
        return "Missing or invalid data/player/quality", 400

    try:
        variant = _xs_manifest(data_id, player_url).get(quality)
    except XsPipelineError as e:
        return f"xtremestream: {e}", 502
    if not variant or not variant.get("durs"):
        return "Unknown quality", 404

    base = f"http://{_proxy.PROXY_HOST}:{_proxy.PROXY_PORT}"
    quotes = urllib.parse.quote
    data_qs = f"data={quotes(data_id, safe='')}&u={quotes(player_url, safe='')}&q={quotes(quality, safe='')}"

    def uri_for(i):
        return f"{base}/xs/segment.ts?{data_qs}&i={i}"

    return _xs_playlist_response(
        _xs_playlist_text(variant["durs"], variant.get("td") or 10, uri_for)
    )


def xs_audio():
    data_id = request.args.get("data", "")
    player_url = request.args.get("u", "")
    lang = request.args.get("lang", "")
    if not data_id or not player_url or not re.fullmatch(r"[A-Za-z0-9_-]+", lang):
        return "Missing or invalid data/player/lang", 400

    try:
        manifest = _xs_manifest(data_id, player_url)
    except XsPipelineError as e:
        return f"xtremestream: {e}", 502
    track = next(
        (t for t in manifest.get("audio") or [] if t.get("lang") == lang), None
    )
    if not track or not track.get("durs"):
        return "Unknown audio track", 404

    base = f"http://{_proxy.PROXY_HOST}:{_proxy.PROXY_PORT}"
    quotes = urllib.parse.quote
    data_qs = f"data={quotes(data_id, safe='')}&u={quotes(player_url, safe='')}&a={quotes(lang, safe='')}"

    def uri_for(i):
        return f"{base}/xs/segment.ts?{data_qs}&i={i}"

    return _xs_playlist_response(
        _xs_playlist_text(track["durs"], track.get("td") or 6, uri_for)
    )


def _xs_media_response(payload: bytes) -> Response:
    return Response(
        payload,
        status=200,
        headers={"Content-Type": "video/mp2t", "Access-Control-Allow-Origin": "*"},
    )


def _xs_fetch_upstream_segment(cdn_hosts, headers, data_id, index, lang, quality):
    """Download one upstream segment (audio passthrough or encrypted video)."""
    if not cdn_hosts:
        return None, None, {}
    host = cdn_hosts[index % len(cdn_hosts)]

    if lang and re.fullmatch(r"[A-Za-z0-9_-]+", lang):
        # Audio segments are clear MPEG-TS (AAC only): direct passthrough.
        url = f"https://{host}/cdn/down/{data_id}/hls_audio/{lang}/seg_{index:03d}.aac"
        return _proxy.fetch_segment(url, headers, request.environ)

    if not re.fullmatch(r"\d+p?", quality):
        return None, None, {}
    url = f"https://{host}/cdn/down/{data_id}/{quality}_enc/{quality}{index}.html"
    return _proxy.fetch_segment(url, headers, request.environ)


def xs_segment():
    data_id = request.args.get("data", "")
    player_url = request.args.get("u", "")
    lang = request.args.get("a", "")
    quality = request.args.get("q", "")
    if not data_id or not player_url:
        return "Missing data or player URL", 400

    try:
        index = int(request.args.get("i", ""))
        if index < 0:
            raise ValueError
    except ValueError:
        return "Invalid segment index", 400

    try:
        cdn_hosts = _xs_manifest(data_id, player_url).get("cdn") or []
    except XsPipelineError as e:
        return f"xtremestream: {e}", 502
    if not cdn_hosts:
        return "Manifest has no CDN host", 502

    if not lang and not re.fullmatch(r"\d+p?", quality):
        return "Missing or invalid quality", 400

    host = cdn_hosts[index % len(cdn_hosts)]
    headers = {"Referer": f"{_xs_origin(player_url)}/"}

    # The player abandoned the transfer (seek/cancel): nothing to serve.
    try:
        result = _xs_fetch_upstream_segment(
            cdn_hosts, headers, data_id, index, lang, quality
        )
    except _proxy._SegmentCancelled:
        return "Cancelled", 499

    if lang and re.fullmatch(r"[A-Za-z0-9_-]+", lang):
        media, status, extra = result
        if media is None:
            return "Error fetching audio segment", 502
        return Response(
            media,
            status=status,
            headers={
                "Content-Type": "video/mp2t",
                "Access-Control-Allow-Origin": "*",
                **extra,
            },
        )

    raw, status, extra = result
    if raw is None:
        return "Error fetching video segment", 502

    # The cached key first; a stale key (re-encoded/re-keyed content,
    # expired token) only shows up as garbage plaintext, so fall back to
    # a fresh boot + key fetch once before giving up.
    error = None
    for force in (False, True):
        try:
            key = _xs_key(data_id, player_url, force=force)
            return _xs_media_response(_xs_decrypt(raw, index, key))
        except (XsPipelineError, ValueError) as e:
            error = e
    log.warning("xtremestream segment %s/%s failed: %s", data_id, index, error)
    return f"xtremestream: {error}", 502


ROUTES = (
    ("/xs/master", xs_master),
    ("/xs/media", xs_media),
    ("/xs/audio", xs_audio),
    ("/xs/segment.ts", xs_segment),
)



def register(app):
    """Attach the /xs/* routes to a built proxy app (idempotent)."""
    if any(r.rule == ROUTES[0][0] for r in app.url_map.iter_rules()):
        return
    for rule, view in ROUTES:
        app.add_url_rule(rule, endpoint=view.__name__, view_func=view)


# Self-registration covers both import orders: proxy.register_pipelines
# fires when the proxy module completes first, this bottom line when this
# module runs first; register() no-ops on a double call.
register(_proxy.app)
