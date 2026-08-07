from curl_cffi import requests as cffi_requests

from .config import portals

scraper = cffi_requests.Session(impersonate="chrome")


class AniVaultExtractor:
    """
    Alternative VO anime extractor backed by the AniVault REST API.

    AniVault resolves stream links from an AniList ID on their servers
    (anikoto / animeheaven sources), so no DOM scraping happens here.
    Sources are tried in order and each produces the same result format as
    the Anivexa extractor (``{"source", "quality", "url", "type",
    "headers", "subtitles"}``).
    """

    def __init__(self):
        self.bases = list(
            dict.fromkeys(
                b
                for b in [
                    portals.get(
                        "anivault", "https://anivault-scraper.vercel.app"
                    ),
                    portals.get("anivault-fallback"),
                ]
                if b
            )
        )
        self.referer = portals.get("anivault-referer", "https://megaplay.buzz/")
        self.referer_animeheaven = portals.get(
            "anivault-referer-animeheaven", "https://animeheaven.me/"
        )
        self._info_cache = {}

    def _get_json(self, path):
        """GET a JSON payload from the first base that answers."""
        for base in self.bases:
            try:
                r = scraper.get(base + path, timeout=20)
                if r.status_code == 200:
                    return r.json()
            except Exception:
                continue
        return None

    def get_info(self, anilist_id):
        """Metadata + site-specific IDs for an AniList ID (cached)."""
        if anilist_id in self._info_cache:
            return self._info_cache[anilist_id]
        data = self._get_json(f"/api/info?anilistId={anilist_id}")
        if data and isinstance(data, dict):
            self._info_cache[anilist_id] = data
            return data
        return {}

    def _subtitles_from_watch(self, watch, referer):
        subtitles = []
        for track in watch.get("subtitles") or []:
            url = track.get("url")
            if not url:
                continue
            lang = track.get("lang") or track.get("language_code") or "?"
            subtitles.append(
                {
                    "lang": lang,
                    "label": lang,
                    "url": url,
                    "format": track.get("format"),
                    "default": bool(track.get("default")),
                    "headers": {"Referer": referer},
                }
            )
        return subtitles or None

    def _entry(self, source, url, stype, referer, watch):
        headers = {"Referer": referer}
        return {
            "source": f"AniVault ({source})",
            "quality": "Auto",
            "url": url,
            "type": stype,
            "headers": headers,
            "subtitles": self._subtitles_from_watch(watch, referer),
            "language": "sub",
        }

    def _extract_anikoto(self, anilist_id, episode):
        watch = self._get_json(
            f"/api/watch/anikoto/{anilist_id}/{episode}/sub"
        )
        if not isinstance(watch, dict):
            return None
        # note/iframeOnly set means no direct playable stream came back
        if watch.get("note") or watch.get("iframeOnly"):
            return None
        url = watch.get("hlsProxyUrl") or watch.get("m3u8")
        if not url:
            return None
        return self._entry("anikoto", url, "M3U8", self.referer, watch)

    def _extract_animeheaven(self, anilist_id, episode):
        info = self.get_info(anilist_id)
        heaven_id = (info.get("siteIds") or {}).get("animeheaven")
        if not heaven_id:
            return None
        watch = self._get_json(
            f"/api/watch/animeheaven/{heaven_id}/{episode}/sub"
        )
        if not isinstance(watch, dict):
            return None
        url = watch.get("mp4ProxyUrl") or watch.get("mp4")
        if not url:
            return None
        return self._entry("animeheaven", url, "MP4", self.referer_animeheaven, watch)

    def extract_vo(self, anilist_id, episode=1):
        """Direct stream entries (anikoto HLS, then animeheaven MP4)."""
        if not anilist_id:
            return []
        results = []
        for extract in (self._extract_anikoto, self._extract_animeheaven):
            try:
                entry = extract(anilist_id, episode)
            except Exception:
                entry = None
            if entry:
                results.append(entry)
        return results


# Instantiate a global instance for easy use
anivault = AniVaultExtractor()
