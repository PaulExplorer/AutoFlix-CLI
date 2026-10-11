import base64
import json
import re
import urllib.parse

from .common import get_scraper

# Voe payload decode ported from ResolveURL's VoeResolver:
# https://github.com/Gujal00/ResolveURL
# Request flow follows mediaflow-proxy's VoeExtractor:
# https://github.com/mhdzumair/mediaflow-proxy (mediaflow_proxy/extractors/voe.py)

def _voe_b64decode(data: str) -> str:
    """Base64 decode helper matching ResolveURL behaviour (padding tolerant)."""
    data = data.strip()
    data += "=" * (-len(data) % 4)
    return base64.b64decode(data).decode("utf-8")

def _voe_decode(ct: str, luts: str) -> dict:
    """Decode a Voe payload. Ported from ResolveURL VoeResolver.voe_decode."""
    lut = [''.join([('\\' + x) if x in '.*+?^${}()|[]\\' else x for x in i]) for i in luts[2:-2].split("','")]
    txt = ''
    for i in ct:
        x = ord(i)
        if 64 < x < 91:
            x = (x - 52) % 26 + 65
        elif 96 < x < 123:
            x = (x - 84) % 26 + 97
        txt += chr(x)
    for i in lut:
        txt = re.sub(i, '', txt)
    ct = _voe_b64decode(txt)
    txt = ''.join([chr(ord(i) - 3) for i in ct])
    txt = _voe_b64decode(txt[::-1])
    return json.loads(txt)

def get_hls_link_voe(url: str, headers: dict = None, config: dict = None) -> str | None:
    """
    Extract HLS/MP4 link from Voe players
    (voe.sx and rotating mirrors like jeremyparticipantanything.com).
    Ported from ResolveURL VoeResolver, structure following
    mediaflow-proxy VoeExtractor:
    https://github.com/mhdzumair/mediaflow-proxy/blob/main/mediaflow_proxy/extractors/voe.py

    Args:
        url: Player URL (https://<voe-mirror>/e/<media_id>)
        headers: HTTP headers for the request
        config: Player config (unused)

    Returns:
        HLS stream URL (preferred) or MP4 fallback, None on failure.
    """
    req_headers = dict(headers or {})

    response = get_scraper().get(url, headers=req_headers, impersonate="chrome")
    response.raise_for_status()
    html = response.text
    web_url = str(response.url or url)

    # Voe rotates domains via a JS redirect:
    # window.location.href = 'https://<new-mirror>/e/<id>'
    for _ in range(3):
        if "const currentUrl" not in html and "window.location.href" not in html:
            break
        m = re.search(r"""window\.location\.href\s*=\s*'([^']+)""", html)
        if not m:
            break
        web_url = m.group(1)
        response = get_scraper().get(web_url, headers=req_headers, impersonate="chrome")
        response.raise_for_status()
        html = response.text
        web_url = str(response.url or web_url)

    m = re.search(r'json">\["([^"]+)"]</script>\s*<script\s*src="([^"]+)', html)
    if not m:
        return None

    ct, js_path = m.group(1), m.group(2)
    js_url = urllib.parse.urljoin(web_url, js_path)
    js_resp = get_scraper().get(js_url, headers=req_headers, impersonate="chrome")
    js_resp.raise_for_status()
    js_html = js_resp.text

    lut_match = re.search(r"(\[(?:'\W{2}'[,\]]){1,9})", js_html)
    if not lut_match:
        return None

    try:
        data = _voe_decode(ct, lut_match.group(1))
    except Exception:
        return None

    if not isinstance(data, dict):
        return None

    # New format: {"source": "<m3u8>", "fallback": [{"file": "<mp4>"}], ...}
    # Old format (ResolveURL): {"file"|"source"|"direct_access_url": ...}
    stream_url = data.get("source") or None
    if not stream_url:
        fallback = data.get("fallback")
        if isinstance(fallback, list) and fallback:
            first = fallback[0]
            if isinstance(first, dict) and first.get("file"):
                stream_url = first["file"]
    if not stream_url:
        stream_url = data.get("file") or data.get("direct_access_url")

    return stream_url
