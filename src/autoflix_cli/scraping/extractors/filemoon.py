import base64
import json
import urllib.parse

from Crypto.Cipher import AES

from .common import get_scraper
from .default import get_hls_link_default

# API flow and AES-256-GCM decryption inspired by mediaflow-proxy:
# https://github.com/mhdzumair/mediaflow-proxy (mediaflow_proxy/extractors/filemoon.py)
# Key-part selection per payload version was reverse-engineered from the
# Filemoon web player bundle.

def _filemoon_b64url(data: str) -> bytes:
    """Decode base64url, tolerating missing padding."""
    padded = data.replace("-", "+").replace("_", "/")
    padding = 4 - len(padded) % 4
    if padding != 4:
        padded += "=" * padding
    return base64.b64decode(padded)

def _filemoon_select_parts(playback: dict, key_parts: list) -> list:
    """Select the key parts used by this payload version.

    The player bundle maps ``version "n"`` (``1``..``20``) to the 1-based
    indices ``[n, 31 - n]`` and concatenates only those two parts. Unknown
    versions fall back to every part (pre-v7 payloads).
    """
    try:
        version = str(playback.get("version", "")).strip()
        index = int(version)
    except (TypeError, ValueError):
        return key_parts
    if not 1 <= index <= 20:
        return key_parts
    wanted = (index, 31 - index)
    if any(i < 1 or i > len(key_parts) for i in wanted):
        return key_parts
    selected = [key_parts[i - 1] for i in wanted]
    if any(not isinstance(part, str) or not part for part in selected):
        return key_parts
    return selected

def get_hls_link_filemoon(url: str, headers: dict, config: dict = None) -> str | None:
    """
    Extract HLS link from Filemoon players (filemoon.sx and mirrors).

    Calls ``https://<host>/api/videos/<code>`` and decrypts the AES-256-GCM
    ``playback`` payload. The key is the concatenation of the two version
    selected ``key_parts`` entries; the GCM tag is the last 16 payload bytes. The HLS source
    (``mime_type == application/vnd.apple.mpegurl``) wins, any other source
    with a URL is the fallback.

    Args:
        url: Player URL (https://<host>/e/<code> or /d/<code>)
        headers: HTTP headers for the request

    Returns:
        HLS stream URL, or None when the video is gone.
    """
    parsed = urllib.parse.urlparse(url)
    code = parsed.path.rstrip("/").split("/")[-1] or ""
    if not code or code in ("e", "d", "embed"):
        return get_hls_link_default(url, headers, config)

    api_url = f"{parsed.scheme}://{parsed.netloc}/api/videos/{code}"
    req_headers = dict(headers or {})
    req_headers.setdefault("Referer", url)

    response = get_scraper().get(api_url, headers=req_headers, impersonate="chrome")
    if response.status_code in (404, 410):
        return None
    response.raise_for_status()

    try:
        data = response.json()
    except ValueError:
        return get_hls_link_default(url, headers, config)

    if isinstance(data, dict) and data.get("error"):
        return None

    playback = (data.get("playback") or {}) if isinstance(data, dict) else {}
    key_parts = playback.get("key_parts") or []
    payload_b64 = playback.get("payload")
    iv_b64 = playback.get("iv")
    if not key_parts or not payload_b64 or not iv_b64:
        return get_hls_link_default(url, headers, config)

    try:
        parts = [
            part
            for part in _filemoon_select_parts(playback, key_parts)
            if isinstance(part, str) and part
        ]
        key = b"".join(_filemoon_b64url(part) for part in parts)
        iv = _filemoon_b64url(iv_b64)
        payload = _filemoon_b64url(payload_b64)
        cipher = AES.new(key, AES.MODE_GCM, nonce=iv)
        decrypted = cipher.decrypt_and_verify(payload[:-16], payload[-16:])
        video_data = json.loads(decrypted.decode("utf-8"))
    except Exception:
        return None

    sources = video_data.get("sources") or []
    for source in sources:
        if (
            isinstance(source, dict)
            and source.get("mime_type") == "application/vnd.apple.mpegurl"
            and source.get("url")
        ):
            return source["url"]
    for source in sources:
        if isinstance(source, dict) and source.get("url"):
            return source["url"]
    return None
