import urllib.parse

from curl_cffi import requests as cffi_requests

from .config import portals

scraper = cffi_requests.Session(impersonate="chrome", allow_redirects="safe")

# Providers do not share a payload shape: mkissa answers with ``sources``
# (``extractedUrl``/``extractedType``/``headers``), animegg with ``streams``.
# Reading only one of them silently dropped every mkissa stream.
WATCH_STREAM_KEYS = ("sources", "streams")

# Referers for providers whose payload carries no headers. Used before
# falling back to the URL host so CDN links still get the player referer.
PROVIDER_REFERERS = {
    "mkissa": "https://mkissa.to/",
    "animegg": "https://www.animegg.org/",
}


class AnimeExtractor:
    """
    Original Version (VO) anime extractor based on a stable REST aggregator.

    Uses the Anivexa-style API: metadata, episode lists and stream links are
    resolved from an AniList ID (no DOM scraping). Multiple public instances
    are tried in order, so a dead deployment only requires changing a URL in
    ``data/source_portal.jsonc`` instead of rewriting a scraper.
    """

    # Providers order by stream quality preference (best first).
    # This mirrors the provider list advertised by the API itself: ``allmanga``
    # is gone, while the newer providers are kept as low-priority fallbacks.
    PROVIDER_PRIORITY = [
        "mkissa",
        "animegg",
        "anikoto",
        "aniwaves",
        "anineko",
        "anidbapp",
        "animenosub",
        "animedunya",
        "animeonsen",
        "senshi",
        "kaa",
        "reanime",
        "anibd",
        "anizone",
        "2dhive",
    ]

    # The /episodes endpoint is slow (~30s / multi-MB payload); requests
    # with the default 20s timeout always fail.
    EPISODES_TIMEOUT = 60

    def __init__(self):
        self.bases = [
            portals.get("aniwatch", "https://anivexa-api-tu4a.onrender.com"),
            portals.get("aniwatch-fallback", "https://anivexa-api-navy.vercel.app"),
        ]
        self.referer = portals.get("aniwatch-referer", "https://anizone.to")
        self._episodes_cache = {}

    def _get_json(self, path, timeout=20):
        """GET a JSON payload from the first base that answers."""
        for base in self.bases:
            try:
                r = scraper.get(base + path, timeout=timeout)
                if r.status_code == 200:
                    return r.json()
            except Exception:
                continue
        return None

    def get_mappings(self, anilist_id):
        """Cross-platform IDs (anidbId, imdbId, malId...) for an AniList ID."""
        data = self._get_json(f"/map/{anilist_id}")
        if data and isinstance(data, dict):
            return data.get("mappings") or {}
        return {}

    def _resolve_anilist_id(self, title):
        """Fallback: resolve an AniList ID from a title when it is missing."""
        if not title:
            return None
        try:
            from ..anilist import anilist_client

            results = anilist_client.search_media(title)
            if results:
                return results[0]["id"]
        except Exception:
            pass
        return None

    def get_episodes(self, anilist_id):
        """Episode lists per provider for a given AniList ID (cached in memory)."""
        cached = self._episodes_cache.get(anilist_id)
        if cached is not None:
            return cached
        data = self._get_json(
            f"/episodes/{anilist_id}", timeout=self.EPISODES_TIMEOUT
        )
        if data and isinstance(data, dict) and any(
            isinstance(v, dict) and isinstance(v.get("episodes"), dict)
            for v in data.values()
        ):
            # Only cache payloads that actually contain episode lists so a
            # transient failure triggers a fresh request next time.
            self._episodes_cache[anilist_id] = data
            return data
        return {}

    @staticmethod
    def _host_referer(url):
        """``https://host/`` for a stream URL, or ``None`` when unparsable."""
        try:
            parsed = urllib.parse.urlsplit(url or "")
        except ValueError:
            return None
        if not parsed.scheme or not parsed.netloc:
            return None
        return f"{parsed.scheme}://{parsed.netloc}/"

    def _subtitles_from_tracks(self, tracks, headers):
        subtitles = []
        for track in tracks or []:
            if not isinstance(track, dict):
                continue
            url = track.get("url")
            if not url:
                continue
            subtitles.append(
                {
                    "lang": track.get("srclang") or track.get("language_code") or "?",
                    "label": track.get("label") or track.get("lang") or "Unknown",
                    "url": url,
                    "format": track.get("format"),
                    "default": bool(track.get("default")),
                    # Subtitle CDNs enforce the same referer as the stream
                    # (often the host player like megaplay.buzz); propagate it.
                    "headers": dict(headers),
                }
            )
        return subtitles or None

    def _stream_headers(self, stream, provider=None, url=None):
        """Playback headers: payload headers, then referer fallbacks."""
        headers = {
            key: value
            for key, value in (stream.get("headers") or {}).items()
            if value
        }
        if not headers.get("Referer"):
            referer = (
                stream.get("referer")
                or PROVIDER_REFERERS.get(provider or "")
                or self._host_referer(url)
                or self.referer + "/"
            )
            headers["Referer"] = referer
        return headers

    @staticmethod
    def _stream_type(stream, url):
        """Map the provider's vocabulary (direct/mp4/iframe) to our types."""
        stype = (stream.get("extractedType") or stream.get("type") or "").lower()
        lowered = url.lower()
        if stype in ("hls", "hls-redirect"):
            return "M3U8"
        if stype in ("mpd", "dash"):
            return "MPD"
        if stype == "mp4":
            return "MP4"
        if stype in ("embed", "iframe", "player"):
            return "Player"
        # ``direct`` (mkissa) is a plain media file, often served from a CDN
        # without an extension: trust it and fall back to the URL suffix.
        if stype == "direct":
            if ".m3u8" in lowered:
                return "M3U8"
            if ".mpd" in lowered:
                return "MPD"
            return "MP4"
        if ".m3u8" in lowered:
            return "M3U8"
        if ".mpd" in lowered:
            return "MPD"
        if ".mp4" in lowered:
            return "MP4"
        return "Player"

    def _stream_entry(self, provider, stream, language, payload_subtitles=None):
        # Providers disagree on field names: mkissa fills extractedUrl/name,
        # animegg only url/type. Normalise both shapes here.
        url = stream.get("extractedUrl") or stream.get("url")
        if not url:
            return None

        out_type = self._stream_type(stream, url)
        server = stream.get("name") or stream.get("server") or provider
        headers = self._stream_headers(stream, provider=provider, url=url)
        tracks = stream.get("subtitles") or payload_subtitles

        return {
            "source": f"Anivexa ({provider} - {server})",
            "quality": "Auto",
            "url": url,
            "type": out_type,
            "headers": headers,
            "subtitles": self._subtitles_from_tracks(tracks, headers),
            "language": language,
        }

    @staticmethod
    def _watch_streams(watch_data):
        """Stream entries from either payload shape (``sources``/``streams``)."""
        for key in WATCH_STREAM_KEYS:
            streams = watch_data.get(key)
            if not isinstance(streams, list):
                continue
            for stream in streams:
                if isinstance(stream, dict):
                    yield stream

    @staticmethod
    def _priority(stream):
        try:
            return float(stream.get("priority") or 0)
        except (TypeError, ValueError):
            return 0.0

    def extract_vo(self, title=None, anilist_id=None, episode=1, lang="sub"):
        """
        Search, deduplication, and sorting.

        Returns the same structure as before:
        ``{"source", "quality", "url", "type", "headers", "subtitles"}``.
        """
        if not anilist_id and title:
            anilist_id = self._resolve_anilist_id(title)
        if not anilist_id:
            return []

        episodes_data = self.get_episodes(anilist_id)
        if not episodes_data:
            return []

        ranked = []
        seen_urls = set()
        for provider in self.PROVIDER_PRIORITY:
            prov = episodes_data.get(provider)
            if not isinstance(prov, dict):
                continue

            episodes = prov.get("episodes")
            if not isinstance(episodes, dict):
                continue

            episode_list = episodes.get(lang) or episodes.get("sub")
            if not episode_list:
                continue

            target = next(
                (ep for ep in episode_list if ep.get("number") == episode), None
            )
            ep_id = target.get("id") if target else None
            if not ep_id:
                continue

            watch_data = self._get_json("/" + ep_id.lstrip("/"))
            if not watch_data:
                continue

            payload_subtitles = watch_data.get("subtitles")
            for stream in self._watch_streams(watch_data):
                entry = self._stream_entry(
                    provider, stream, lang, payload_subtitles
                )
                if entry and entry["url"] not in seen_urls:
                    seen_urls.add(entry["url"])
                    ranked.append((self._priority(stream), entry))

        # Best provider-declared priority first; the stable sort keeps the
        # provider order (and the payload order) as the tie-breaker.
        ranked.sort(key=lambda item: item[0], reverse=True)
        return [entry for _, entry in ranked]


# Instantiate a global instance for easy use
goldenanime = AnimeExtractor()
