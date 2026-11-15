"""MeowTV stream extractor (TMDB IDs, plain JSON API).

MeowTV exposes a small JSON API instead of a scraped page: one single-use
ticket authorises the stream request, and the answer is an encrypted blob the
public ``enc-dec.app`` service decrypts. Each server id returns one HLS
manifest in a given audio language, and the subtitle list is a separate JSON
endpoint.
"""

from curl_cffi import requests as cffi_requests

from .config import portals

scraper = cffi_requests.Session(impersonate="chrome", allow_redirects="safe")

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36"
)

# Audio servers, best first. ``dcloud`` serves the original track ("Auto"),
# the others are dubs; a server that does not have the title answers 404 and
# is simply skipped.
SERVERS = ("dcloud", "english", "tik")

# Referer expected by the stream and subtitle CDNs.
REFERER = "https://meowtv.ru/"


class MeowTVExtractor:
    """Resolve a TMDB movie/episode to HLS streams and subtitle tracks."""

    def __init__(self):
        self.api = portals.get("meowtv", "https://api.meowtv.ru").rstrip("/")
        self.decrypt_api = portals.get(
            "multi-decrypt", "https://enc-dec.app/api"
        ).rstrip("/")

    def _headers(self):
        return {
            "User-Agent": USER_AGENT,
            "Origin": REFERER.rstrip("/"),
            "Referer": REFERER,
        }

    def _ticket(self):
        """A fresh single-use ticket (the API rejects reused ones)."""
        try:
            response = scraper.post(
                f"{self.api}/streams/ticket", headers=self._headers(), timeout=15
            )
            if response.status_code != 200:
                return None
            return (response.json() or {}).get("ticket")
        except Exception:
            return None

    def _get_json(self, path):
        ticket = self._ticket()
        if not ticket:
            return None
        headers = {**self._headers(), "X-Stream-Ticket": ticket}
        try:
            response = scraper.get(f"{self.api}{path}", headers=headers, timeout=20)
            if response.status_code != 200:
                return None
            return response.json()
        except Exception:
            return None

    def _decrypt(self, data):
        if not data:
            return None
        try:
            response = scraper.post(
                f"{self.decrypt_api}/dec-meowtv", json={"data": data}, timeout=20
            )
            if response.status_code != 200:
                return None
            payload = response.json()
        except Exception:
            return None
        if not isinstance(payload, dict) or payload.get("status") != 200:
            return None
        return payload.get("result")

    @staticmethod
    def _path(tmdb_id, season=None, episode=None):
        if season is None or episode is None:
            return f"/movie/{int(tmdb_id)}"
        return f"/tv/{int(tmdb_id)}/{int(season)}/{int(episode)}"

    def subtitles(self, tmdb_id, season=None, episode=None):
        """Subtitle tracks for a movie or an episode (VTT, many languages)."""
        if not tmdb_id:
            return []
        data = self._get_json(f"/subs{self._path(tmdb_id, season, episode)}")
        if not isinstance(data, list):
            return []

        headers = {"User-Agent": USER_AGENT, "Referer": REFERER}
        tracks = []
        seen = set()
        for track in data:
            if not isinstance(track, dict):
                continue
            url = track.get("file")
            label = track.get("label") or "Unknown"
            # The endpoint lists several uploads per language; keep the first
            # one so the player menu has one track per language.
            if not url or label in seen:
                continue
            seen.add(label)
            tracks.append(
                {
                    "lang": label,
                    "label": label,
                    "url": url,
                    "format": "vtt",
                    "headers": dict(headers),
                }
            )
        return tracks

    def streams(self, tmdb_id, season=None, episode=None):
        """One entry per server that has the title."""
        if not tmdb_id:
            return []

        path = self._path(tmdb_id, season, episode)
        subtitles = self.subtitles(tmdb_id, season, episode)

        results = []
        seen = set()
        for server in SERVERS:
            data = self._get_json(f"/streams{path}?s={server}")
            decrypted = self._decrypt(data)
            url = (decrypted or {}).get("url")
            if not url or url in seen:
                continue
            seen.add(url)
            language = decrypted.get("language") or "Auto"
            headers = {
                "User-Agent": USER_AGENT,
                "Referer": REFERER,
                **(decrypted.get("headers") or {}),
            }
            results.append(
                {
                    "source": f"MeowTV ({server} - {language})",
                    "quality": "Auto",
                    "url": url,
                    "type": "M3U8" if ".m3u8" in url.lower() else "MP4",
                    "headers": headers,
                    "subtitles": subtitles or None,
                }
            )
        return results


# Instantiate a global instance for easy use
meowtv_extractor = MeowTVExtractor()
