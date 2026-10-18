import urllib.parse

from bs4 import BeautifulSoup

from ..deobfuscate import deobfuscate
from .common import (
    _extract_jwplayer_source,
    _extract_streamhide_candidates,
    _fetch_embed_page,
    _stream_alive,
    _unpack_all,
    extract_hls_url,
    extract_video_url,
)

MAX_IFRAME_DEPTH = 3

def get_hls_link_default(
    url: str, headers: dict, config: dict = None, _depth: int = 0
) -> str:
    """
    Extract stream link from default player.

    Config keys (all optional):
        no-header: send the request without HTTP headers
        url-replacements: dict of str replacements applied to the deobfuscated
            page before searching for the stream URL

    The page is searched in two forms: raw (HTML attributes stay intact)
    and deobfuscated (unpacked JavaScript, where packed players hide the
    URL). Extractions, in order:
        - EarnVids/StreamHide links blob (hls4 > hls3 > hls2)
        - jwplayer sources:[{file:"..."}] blocks
        - HLS playlist URL (master.*, *.m3u8)          [primary]
        - classic video file URL (.mp4, .webm, .m4v, .mov)
        - iframe redirect (container players)
    """
    config = config or {}

    if config.get("no-header") or (config.get("m3u8-extractor") or {}).get("no-header"):
        headers = {}

    response = _fetch_embed_page(url, headers)
    response.raise_for_status()
    page_url = str(response.url or url)

    code = deobfuscate(response.text)
    try:
        unpacked = _unpack_all(response.text)
    except Exception:
        unpacked = code
    for old, new in (config.get("url-replacements") or {}).items():
        code = code.replace(old, new)
        unpacked = unpacked.replace(old, new)

    # 1. EarnVids/StreamHide links blob (unpacked first, then raw). The
    #    renditions sit on different CDNs; one can be dead for everyone
    #    while the next still serves, so play the first live one — the
    #    web player does the same with links.hls4||links.hls3||links.hls2.
    seen_candidates: list[str] = []
    for text in (unpacked, code, response.text):
        for candidate in _extract_streamhide_candidates(text, page_url):
            if candidate not in seen_candidates:
                seen_candidates.append(candidate)
    if seen_candidates:
        for candidate in seen_candidates:
            if _stream_alive(candidate, headers):
                return candidate
        # All candidates rejected: hand back the best-priority one so the
        # probe reports the real error instead of "no stream found".
        return seen_candidates[0]

    # 2. jwplayer sources:[{file:"..."}] blocks (unpacked first, then raw).
    for text in (unpacked, code, response.text):
        stream_url = _extract_jwplayer_source(text, page_url)
        if stream_url:
            return stream_url

    # 3. HLS playlist URL. Raw page first (JS beautification turns
    # "https://" into "https: //", so it cannot be trusted for plain HTML),
    # then deobfuscated JavaScript.
    stream_url = (
        extract_hls_url(response.text) or extract_hls_url(code) or extract_hls_url(unpacked)
    )
    if stream_url:
        return stream_url

    # 4. Classic video file URL (direct MP4/WebM players)
    stream_url = (
        extract_video_url(response.text)
        or extract_video_url(code)
        or extract_video_url(unpacked)
    )
    if stream_url:
        return stream_url

    # 5. iframe redirect (container players)
    soup = BeautifulSoup(response.text, "html.parser")
    iframe = soup.find("iframe")
    if iframe and iframe.get("src"):
        iframe_src = iframe["src"].strip()
        if iframe_src.startswith("//"):
            iframe_src = "https:" + iframe_src
        elif iframe_src.startswith("/"):
            parsed = urllib.parse.urlparse(url)
            iframe_src = f"{parsed.scheme}://{parsed.netloc}{iframe_src}"
        elif not iframe_src.startswith("http"):
            iframe_src = "https://" + iframe_src

        # Guard against self-reference / deep chains to avoid infinite recursion
        if iframe_src != url and _depth < MAX_IFRAME_DEPTH:
            from ..player import get_hls_link  # deferred: dispatcher owns the registry

            # First: resolve through a registered player if the iframe points to one
            resolved = get_hls_link(iframe_src, headers)
            if resolved:
                return resolved
            # Then: try generic extraction for unregistered inner players
            return get_hls_link_default(iframe_src, headers, config, _depth + 1)

    return None
