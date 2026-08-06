from curl_cffi import requests as cffi_requests

from .config import portals

scraper = cffi_requests.Session(impersonate="chrome")


class AnimeExtractor:
    """
    Original Version (VO) anime extractor based on a stable REST aggregator.

    Uses the Anivexa-style API: metadata, episode lists and stream links are
    resolved from an AniList ID (no DOM scraping). Multiple public instances
    are tried in order, so a dead deployment only requires changing a URL in
    ``data/source_portal.jsonc`` instead of rewriting a scraper.
    """

    # Providers order by stream quality preference (best first)
    PROVIDER_PRIORITY = [
        "anizone",
        "anikoto",
        "kaa",
        "animegg",
        "reanime",
        "2dhive",
        "allmanga",
        "anibd",
    ]

    def __init__(self):
        self.bases = [
            portals.get("aniwatch", "https://anivexa-api-production.up.railway.app"),
            portals.get("aniwatch-fallback", "https://anivexa-api.vercel.app"),
        ]
        self.referer = portals.get("aniwatch-referer", "https://anizone.to")

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
        """Episode lists per provider for a given AniList ID."""
        data = self._get_json(f"/episodes/{anilist_id}")
        if data and isinstance(data, dict):
            return data
        return {}

    def _subtitles_from_stream(self, stream):
        subtitles = []
        for track in stream.get("subtitles") or []:
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
                }
            )
        return subtitles or None

    def _stream_entry(self, provider, stream, language):
        url = stream.get("url")
        if not url:
            return None

        stype = (stream.get("type") or "").lower()
        if stype in ("hls", "hls-redirect"):
            out_type = "M3U8"
        elif stype == "mp4":
            out_type = "MP4"
        elif stype == "embed":
            out_type = "Player"
        elif ".m3u" in url.lower():
            out_type = "M3U8"
        elif ".mp4" in url.lower():
            out_type = "MP4"
        else:
            out_type = "Player"

        server = stream.get("server") or provider
        headers = {"Referer": self.referer + "/"}
        stream_referer = stream.get("referer")
        if stream_referer:
            headers["Referer"] = stream_referer

        return {
            "source": f"Anivexa ({provider} - {server})",
            "quality": "Auto",
            "url": url,
            "type": out_type,
            "headers": headers,
            "subtitles": self._subtitles_from_stream(stream),
            "language": language,
        }

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

        results = []
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

            for stream in watch_data.get("streams") or []:
                entry = self._stream_entry(provider, stream, lang)
                if entry and entry["url"] not in seen_urls:
                    seen_urls.add(entry["url"])
                    results.append(entry)

        return results


# Instantiate a global instance for easy use
goldenanime = AnimeExtractor()
