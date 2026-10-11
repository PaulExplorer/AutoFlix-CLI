import json
import re
import threading
import urllib.parse

from curl_cffi import requests

from ...proxy import DNS_OPTIONS

# Search patterns and the unpack strategy below are inspired by:
# - ResolveURL helpers (get_media_url / scrape_sources / get_packed_data)
#   https://github.com/Gujal00/ResolveURL
# - mediaflow-proxy StreamWish / LuluStream extractors (incl. eval_solver)
#   https://github.com/mhdzumair/mediaflow-proxy

_thread_local = threading.local()

def get_scraper() -> requests.Session:
    """Return the HTTP session bound to the calling thread."""
    session = getattr(_thread_local, "scraper", None)
    if session is None:
        session = requests.Session(curl_options=DNS_OPTIONS, allow_redirects="safe")
        _thread_local.scraper = session
    return session

scraper = get_scraper()

RESTRICTED_MARKER = "Video embed restricted for this domain"

FALLBACK_REFERERS = ("https://lecteurvideo.com/",)

def _fetch_embed_page(url: str, headers: dict):
    """GET an embed page, retrying with alternate Referers when rejected.

    Some hosts answer 403 (fsvid) or 200 with a "Video embed restricted"
    marker (EarnVids/StreamHide/uqload family) unless the Referer domain is
    allowlisted. Candidates are tried in order: the caller Referer (or the
    embed host root when missing), the embed host root, then the universal
    fallback. The first neither-403-nor-restricted page is returned.
    """
    req_headers = dict(headers or {})
    host = urllib.parse.urlparse(url).hostname or ""
    host_root = f"https://{host}/" if host else ""

    candidates: list = [req_headers.get("Referer") or host_root]
    if host_root and host_root not in candidates:
        candidates.append(host_root)
    for fallback in FALLBACK_REFERERS:
        if fallback not in candidates:
            candidates.append(fallback)

    last = None
    for referer in candidates:
        attempt_headers = dict(req_headers)
        if referer:
            attempt_headers["Referer"] = referer
        try:
            response = get_scraper().get(
                url, headers=attempt_headers, impersonate="chrome"
            )
        except Exception:
            continue
        last = response
        if response.status_code == 403:
            continue
        try:
            response.raise_for_status()
        except Exception:
            continue
        if RESTRICTED_MARKER not in response.text:
            return response
    if last is not None:
        return last
    return get_scraper().get(url, headers=req_headers, impersonate="chrome")

def _unpack_all(html: str) -> str:
    """Unpack every Dean Edwards eval block and append the results to the HTML.

    The single-shot whole-page unpack misses pages with several eval blocks
    (or HTML wrappers the unpacker chokes on); searching raw + unpacked text
    together is what ResolveURL/mediaflow-proxy do.
    """
    from jsbeautifier.unpackers import packer as js_packer

    parts = [html]
    for match in re.finditer(
        r"eval\(function\(p,a,c,k,e,d.*?</script>", html, re.DOTALL | re.IGNORECASE
    ):
        try:
            if js_packer.detect(match.group(0)):
                parts.append(js_packer.unpack(match.group(0)))
        except Exception:
            continue
    if len(parts) == 1:
        try:
            if js_packer.detect(html):
                parts.append(js_packer.unpack(html))
        except Exception:
            pass
    return "\n".join(parts)

def _extract_streamhide_links(text: str, base_url: str) -> str | None:
    """Extract a stream from EarnVids/StreamHide-style ``links={...}`` blobs.

    The player boots with ``sources:[{file:links.hls4||links.hls3||links.hls2}]``
    where ``links`` maps renditions to URLs (``hls4`` is usually a relative
    ``/stream/...`` path). Same priority as the web player.
    """
    match = re.search(r"links\s*=\s*(\{[^;]*\})", text)
    if not match:
        return None
    try:
        links = json.loads(match.group(1).replace("\\/", "/"))
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(links, dict):
        return None
    for key in ("hls4", "hls3", "hls2"):
        candidate = links.get(key)
        if candidate and isinstance(candidate, str):
            return urllib.parse.urljoin(base_url, candidate.strip())
    return None

def _extract_jwplayer_source(text: str, base_url: str) -> str | None:
    """Extract a ``sources:[{file:"..."}]`` URL (jwplayer setup blocks)."""
    match = re.search(
        r'sources\s*:\s*\[\s*\{\s*file\s*:\s*["\']([^"\']+)["\']',
        text,
        re.IGNORECASE,
    )
    if not match:
        return None
    return urllib.parse.urljoin(base_url, match.group(1).strip())

def extract_hls_url(unpacked_code):
    pattern = r'(https?://[^"\'\\\s]*master\.txt[^"\'\\\s]*)'
    match = re.search(pattern, unpacked_code)
    if match:
        return match.group(1)

    pattern = r'(https?://[^"\'\\\s]*master\.m3u8[^"\'\\\s]*)'
    match = re.search(pattern, unpacked_code)
    if match:
        return match.group(1)

    pattern = r'(https?://[^"\'\\\s]*\.m3u8[^"\'\\\s]*)'
    match = re.search(pattern, unpacked_code)
    if match:
        return match.group(1)

    return None

def extract_video_url(unpacked_code):
    pattern = r'(https?://[^"\'\\\s]*\.(?:mp4|webm|m4v|mov)[^"\'\\\s]*)'
    match = re.search(pattern, unpacked_code)
    if match:
        return match.group(1)

    return None
