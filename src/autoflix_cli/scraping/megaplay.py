"""MegaPlay stream extractor (AniList IDs, no title search).

MegaPlay is the player embedded by several anime sites (HiAnime, AniKoto...).
Unlike the aggregator used by :mod:`goldenanime`, it accepts an AniList ID and
an episode number directly: no title matching, no season mapping, so it keeps
working when catalogues are reordered. The player answers with an encrypted
payload that the public ``enc-dec.app`` service decrypts (the same service
already used as VidLink's token fallback).
"""

import re

from curl_cffi import requests as cffi_requests

from .config import portals

scraper = cffi_requests.Session(impersonate="chrome", allow_redirects="safe")

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36"
)

# ``<title>File 13461 - MegaPlay</title>`` on success, ``Error`` otherwise.
_CONTENT_ID_RE = re.compile(r"<title>File (\d+) - MegaPlay</title>")

# MegaPlay voice tracks. Anything else falls back to the subbed version.
AUDIO_TYPES = ("sub", "dub")


class MegaPlayExtractor:
    """Resolve an AniList episode to one HLS manifest plus its subtitles."""

    def __init__(self):
        self.base = portals.get("megaplay", "https://megaplay.buzz").rstrip("/")
        self.decrypt_api = portals.get(
            "multi-decrypt", "https://enc-dec.app/api"
        ).rstrip("/")

    def _headers(self):
        return {
            "User-Agent": USER_AGENT,
            "Origin": self.base,
            "Referer": self.base + "/",
            "X-Requested-With": "XMLHttpRequest",
        }

    def _get_text(self, url, params=None):
        try:
            response = scraper.get(
                url, params=params, headers=self._headers(), timeout=20
            )
        except Exception:
            return None
        if response.status_code != 200:
            return None
        return response.text

    def _get_json(self, url, params=None):
        try:
            response = scraper.get(
                url, params=params, headers=self._headers(), timeout=20
            )
            if response.status_code != 200:
                return None
            return response.json()
        except Exception:
            return None

    def _decrypt(self, text):
        """Decrypt a MegaPlay payload through the public enc-dec service."""
        if not text:
            return None
        try:
            response = scraper.post(
                f"{self.decrypt_api}/dec-megaplay",
                json={"text": text},
                timeout=20,
            )
            if response.status_code != 200:
                return None
            payload = response.json()
        except Exception:
            return None
        if not isinstance(payload, dict) or payload.get("status") != 200:
            return None
        return payload.get("result")

    def content_id(self, anilist_id, episode, audio="sub"):
        """MegaPlay's internal file id for an AniList episode, or ``None``."""
        text = self._get_text(
            f"{self.base}/stream/ani/{int(anilist_id)}/{int(episode)}/{audio}"
        )
        if not text:
            return None
        match = _CONTENT_ID_RE.search(text)
        return match.group(1) if match else None

    def sources(self, content_id):
        """Encrypted sources payload for an internal content id."""
        return self._get_json(
            f"{self.base}/stream/getSources",
            params={"id": content_id, "platform": "OTHER"},
        )

    @staticmethod
    def _subtitles(tracks, headers):
        subtitles = []
        for track in tracks or []:
            if not isinstance(track, dict):
                continue
            if (track.get("kind") or "").lower() != "captions":
                continue
            url = track.get("file")
            if not url:
                continue
            label = track.get("label") or "Unknown"
            subtitles.append(
                {
                    "lang": label,
                    "label": label,
                    "url": url,
                    "default": bool(track.get("default")),
                    # The subtitle CDN enforces the player referer too.
                    "headers": dict(headers),
                }
            )
        return subtitles or None

    def streams(self, anilist_id, episode, audio="sub"):
        """Stream entries for one AniList episode (``sub`` or ``dub``)."""
        if not anilist_id or not episode:
            return []
        audio = audio if audio in AUDIO_TYPES else "sub"

        content_id = self.content_id(anilist_id, episode, audio)
        if not content_id:
            return []

        payload = self.sources(content_id)
        if not isinstance(payload, dict) or not payload.get("enc"):
            return []

        decrypted = self._decrypt(payload["enc"])
        url = (decrypted or {}).get("file")
        if not url:
            return []

        headers = {"User-Agent": USER_AGENT, "Referer": self.base + "/"}
        return [
            {
                "source": f"MegaPlay ({audio})",
                "quality": "Auto",
                "url": url,
                "type": "M3U8" if ".m3u8" in url.lower() else "MP4",
                "headers": headers,
                "subtitles": self._subtitles(payload.get("tracks"), headers),
                "language": audio,
            }
        ]


# Instantiate a global instance for easy use
megaplay_extractor = MegaPlayExtractor()
