import base64
import ctypes
import ctypes.util
import struct
import time

from curl_cffi import requests as cffi_requests

from .config import portals

scraper = cffi_requests.Session(impersonate="chrome", allow_redirects="safe")

# Public key embedded in VidLink's own web player JS (de-facto public).
# It encrypts the TMDB ID + expiry timestamp with XSalsa20-Poly1305.
VIDLINK_KEY_HEX = "c75136c5668bbfe65a7ecad431a745db68b5f381555b38d8f6c699449cf11fcd"
VIDLINK_KEY = bytes.fromhex(VIDLINK_KEY_HEX)
VIDLINK_NONCE = bytes(24)

# VidLink's stream CDN only serves media to requests presenting these values.
CANON_HEADERS = {"Referer": "https://filmboom.top/", "Origin": "https://filmboom.top"}

QUALITY_ORDER = ["1080", "720", "480", "360"]


def _load_sodium():
    for name in ("libsodium.so.26", "libsodium.so", "sodium"):
        try:
            return ctypes.CDLL(name)
        except OSError:
            continue
    lib_path = ctypes.util.find_library("sodium")
    if lib_path:
        try:
            return ctypes.CDLL(lib_path)
        except OSError:
            pass
    return None


_sodium = _load_sodium()


def _encrypt_token_native(media_id):
    """Encrypt the media token with XSalsa20-Poly1305 using libsodium."""
    if not _sodium:
        return None
    try:
        timestamp = int(time.time() + 480)
        message = media_id.encode("utf-8") + struct.pack(">Q", timestamp)
        mlen = len(message)
        # crypto_secretbox_MACBYTES = 16
        out = ctypes.create_string_buffer(mlen + 16)
        ret = _sodium.crypto_secretbox_easy(out, message, mlen, VIDLINK_NONCE, VIDLINK_KEY)
        if ret != 0:
            return None
        full_payload = VIDLINK_NONCE + out.raw
        return base64.urlsafe_b64encode(full_payload).decode("utf-8").rstrip("=")
    except Exception:
        return None


def _encrypt_token_fallback(media_id, decrypt_api):
    """Fallback token encryption through the public enc-dec.app API (VidLink compat)."""
    try:
        r = scraper.get(f"{decrypt_api}/enc-vidlink?text={media_id}", timeout=8)
        if r.status_code == 200:
            data = r.json()
            if data.get("status") == 200:
                return data.get("result")
    except Exception:
        pass
    return None


class MediaExtractor:
    """Movie and Series extractor backed by VidLink (auto-hosted API).

    Returns direct MP4/HLS links with available subtitle tracks. The stream
    CDN requires VidLink's player referer/origin (filmboom.top).
    """

    def __init__(self):
        # --- Source URLs loaded from source_portal.jsonc ---
        self.vidlink_api = portals.get("vidlink", "https://vidlink.pro")
        decrypt_api = portals.get("multi-decrypt", "https://enc-dec.app/api")
        self.decrypt_api = decrypt_api.rstrip("/")

    def _cdn_headers(self, quality_headers=None):
        """Normalize per-quality headers onto VidLink's CDN referer/origin."""
        rh = oh = None
        if quality_headers:
            rh = quality_headers.get("referer") or quality_headers.get("Referer")
            oh = quality_headers.get("origin") or quality_headers.get("Origin")
        return {
            "Referer": rh or CANON_HEADERS["Referer"],
            "Origin": oh or CANON_HEADERS["Origin"],
        }

    def _build_entries(self, data, media_id):
        """Turn a VidLink API payload into AutoFlix stream entries."""
        stream_info = data.get("stream") or {}
        stype = (stream_info.get("type") or "").lower()

        candidates = []
        qualities = stream_info.get("qualities") or {}
        ordered = QUALITY_ORDER + [
            q for q in qualities if q not in QUALITY_ORDER
        ]
        for q in ordered:
            entry = qualities.get(q) or {}
            url = entry.get("url")
            if url:
                candidates.append((f"{q}p", url, entry.get("headers")))

        if not candidates:
            fallback_url = stream_info.get("playlist") or stream_info.get("url")
            if fallback_url:
                candidates.append(("Auto", fallback_url, None))

        subtitles = []
        for t in data.get("captions") or []:
            if not t.get("url"):
                continue
            lang = t.get("language") or "en"
            subtitles.append(
                {
                    "lang": lang,
                    "label": t.get("label") or lang.upper(),
                    "url": t["url"],
                    "headers": dict(CANON_HEADERS),
                }
            )

        results = []
        seen = set()
        for quality, url, q_headers in candidates:
            if url in seen:
                continue
            seen.add(url)
            is_hls = stype == "hls" or ".m3u8" in url.lower()
            results.append(
                {
                    "source": "VidLink",
                    "quality": quality,
                    "url": url,
                    "type": "M3U8" if is_hls else "MP4",
                    "subtitles": subtitles or None,
                    "headers": self._cdn_headers(q_headers),
                }
            )
        return results

    def search_vidlink(self, tmdb_id, season=None, episode=None):
        """Extraction via VidLink. Direct HLS/MP4 by TMDB ID."""
        if not tmdb_id:
            return []

        media_id = str(tmdb_id)
        token = _encrypt_token_native(media_id)
        if not token:
            token = _encrypt_token_fallback(media_id, self.decrypt_api)
        if not token:
            return []

        if season is not None and episode is not None:
            api_url = (
                f"{self.vidlink_api}/api/b/tv/{token}/{season}/{episode}"
                "?multiLang=1"
            )
        else:
            api_url = f"{self.vidlink_api}/api/b/movie/{token}?multiLang=1"

        try:
            r = scraper.get(
                api_url,
                headers={
                    "Accept": "application/json",
                    "Origin": self.vidlink_api,
                    "Referer": f"{self.vidlink_api}/",
                },
                timeout=15,
            )
            if r.status_code != 200:
                return []
            data = r.json()
        except Exception:
            return []

        if not isinstance(data, dict) or not data.get("stream"):
            return []

        return self._build_entries(data, media_id)

    def extract(
        self,
        title=None,
        tmdb_id=None,
        imdb_id=None,
        year=None,
        season=None,
        episode=None,
    ):
        """Main search method."""
        if tmdb_id:
            return self.search_vidlink(tmdb_id, season, episode)
        return []


# Instantiate a global instance for easy use
goldenms_extractor = MediaExtractor()
