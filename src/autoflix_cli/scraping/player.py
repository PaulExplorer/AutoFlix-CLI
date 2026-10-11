from . import arkanime
from curl_cffi import requests
from .deobfuscate import deobfuscate
from bs4 import BeautifulSoup
from ..proxy import DNS_OPTIONS
from ..config_loader import load_config
from ..defaults import DEFAULT_PLAYERS, DEFAULT_NEW_URL, DEFAULT_KAKAFLIX_PLAYERS
from ..cli_utils import print_warning
import re, base64
import urllib.parse
from urllib.parse import quote
import json
import binascii
import os
import time
from Crypto.Cipher import AES
from Crypto.Util.Padding import unpad

import threading

# curl_cffi sessions are not thread-safe: sharing one across the concurrent
# embed resolution of the auto source picker corrupts in-flight requests.
# Each thread therefore gets its own session, while the main thread keeps
# reusing a single pooled connection for the usual sequential flow.
_thread_local = threading.local()


def get_scraper() -> requests.Session:
    """Return the HTTP session bound to the calling thread."""
    session = getattr(_thread_local, "scraper", None)
    if session is None:
        session = requests.Session(curl_options=DNS_OPTIONS, allow_redirects="safe")
        _thread_local.scraper = session
    return session


scraper = get_scraper()

# Local data dir (dev override, not shipped in the package wheel):
# src/autoflix_cli/scraping/player.py -> ../../../data
LOCAL_DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "..", "data")

REMOTE_PLAYERS_URL = (
    "https://raw.githubusercontent.com/PaulExplorer/AutoFlix-CLI/refs/heads/main/data/players_info.jsonc"
)
REMOTE_NEW_URL_URL = (
    "https://raw.githubusercontent.com/PaulExplorer/AutoFlix-CLI/refs/heads/main/data/new_url.jsonc"
)
REMOTE_KAKAFLIX_URL = (
    "https://raw.githubusercontent.com/PaulExplorer/AutoFlix-CLI/refs/heads/main/data/kakaflix_players.jsonc"
)


# Player mapping: domain name -> parser type / configuration.
# Order is: defaults -> remote -> local file (dev override in data/).
players = load_config(
    REMOTE_PLAYERS_URL,
    DEFAULT_PLAYERS,
    os.path.join(LOCAL_DATA_DIR, "players_info.jsonc"),
)

# URL replacements for compatibility
new_url = load_config(
    REMOTE_NEW_URL_URL,
    DEFAULT_NEW_URL,
    os.path.join(LOCAL_DATA_DIR, "new_url.jsonc"),
)

# kakaflix supported players
kakaflix_players = load_config(
    REMOTE_KAKAFLIX_URL,
    DEFAULT_KAKAFLIX_PLAYERS,
    os.path.join(LOCAL_DATA_DIR, "kakaflix_players.jsonc"),
)


# Hosts of the XUpload/EarnVids/StreamHide family refuse embeds whose
# Referer domain is not allowlisted and answer 200 with this marker instead
# of a player. lecteurvideo.com is allowlisted everywhere (it is the proxy
# Coflix itself routes embeds through), so it is used as a fallback.
RESTRICTED_MARKER = "Video embed restricted for this domain"
FALLBACK_REFERERS = ("https://lecteurvideo.com/",)

DEFAULT_SCRAPER_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


def _fetch_embed_page(url: str, headers: dict):
    """GET an embed page, retrying with alternate Referers when rejected.

    Some hosts answer 403 (fsvid) or 200 with a "Video embed restricted"
    marker (EarnVids/StreamHide/uqload family) unless the Referer domain is
    allowlisted. Candidates are tried in order: the caller Referer (or the
    embed host root when missing), the embed host root, then the universal
    fallback. The first neither-403-nor-restricted page is returned.
    """
    req_headers = dict(headers or {})
    req_headers.setdefault("User-Agent", DEFAULT_SCRAPER_UA)
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


def get_hls_link_xupload(url: str, headers: dict, config: dict = None) -> str | None:
    """Extract the stream from XUpload-based hosts (vidzy, fsvid, uqload...).

    The player setup hides the source in a base64 blob decoded in-browser as::

        b64decode -> reverse -> XOR((0x3D + i*89 + H + BC) & 255)

    where ``H`` is the embed hostname checksum and ``BC`` a measurement the
    page takes in a real browser (``offsetWidth`` of a 50% child inside a
    ``calc(1in + Npx)`` box, i.e. ``BC = (96 + N) / 2`` at standard DPI).
    ``N`` is read from the page itself; when absent, ``BC`` is brute-forced
    (256 tries on ~200 bytes, negligible) and the first ``https?://`` result
    wins. A wrong key yields garbage, never a link.
    """
    response = _fetch_embed_page(url, headers)
    html = response.text
    page_url = str(response.url or url)
    hostname = urllib.parse.urlparse(page_url).hostname or ""

    try:
        unpacked = _unpack_all(html)
    except Exception:
        unpacked = html

    blobs: list[str] = []
    for text in (html, unpacked):
        for found in re.findall(
            r"\}\)\(\s*[\"']([^\"']{50,})[\"']\s*\)", text
        ):
            if found not in blobs:
                blobs.append(found)
    if not blobs:
        return None

    seed = sum(hostname.encode("utf-8", "ignore")) & 255
    width = re.search(r"1in \+ (\d+)px", unpacked)
    bc_values: list[int] = []
    if width:
        bc_values.append((96 + int(width.group(1))) // 2)
    bc_values.extend(bc for bc in range(256) if bc not in bc_values)

    has_browser_check = "offsetWidth" in unpacked or "+BC" in unpacked
    for blob in blobs:
        try:
            raw = base64.b64decode(blob)
        except (binascii.Error, ValueError):
            continue
        raw = raw[::-1]
        for bc in bc_values:
            out = bytes(
                value ^ ((0x3D + i * 89 + seed + bc) & 255)
                for i, value in enumerate(raw)
            )
            try:
                candidate = out.decode("utf-8")
            except UnicodeDecodeError:
                continue
            if re.match(r"^https?://[^\s\"'\\]+$", candidate):
                return candidate
            # Old template without the browser check: only the seed matters.
            if not has_browser_check:
                break
    return None


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


# Maximum depth for following iframe redirects in get_hls_link_default.
# Prevents infinite recursion on players that embed each other in a loop.
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

    # 1. EarnVids/StreamHide links blob (unpacked first, then raw).
    for text in (unpacked, code, response.text):
        stream_url = _extract_streamhide_links(text, page_url)
        if stream_url:
            return stream_url

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
            # First: resolve through a registered player if the iframe points to one
            resolved = get_hls_link(iframe_src, headers)
            if resolved:
                return resolved
            # Then: try generic extraction for unregistered inner players
            return get_hls_link_default(iframe_src, headers, config, _depth + 1)

    return None


def get_hls_link_embed4me(embed_url: str, headers: dict = None, config: dict = None) -> str:
    """
    Extract HLS link from embed4me player.
    Code adapted from: https://github.com/SertraFurr/Anime-Sama-Downloader/blob/main/src/utils/extract/extract_embed4me_video_source.py

    Args:
        embed_url: The embed URL of the player.

    Returns:
        The HLS stream URL or None if not found.
    """

    KEY = b"kiemtienmua911ca"
    IV = b"1234567890oiuytr"

    def _decrypt_data(hex_str):
        try:
            data = binascii.unhexlify(hex_str)
            cipher = AES.new(KEY, AES.MODE_CBC, IV)
            decrypted = unpad(cipher.decrypt(data), AES.block_size)
            return decrypted.decode("utf-8")
        except Exception:
            return None

    match = re.search(r"#([a-zA-Z0-9]+)", embed_url)
    if not match:
        match = re.search(r"[?&]id=([a-zA-Z0-9]+)", embed_url)
    if not match:
        return None

    video_id = match.group(1)
    url_root = "https://" + embed_url.split("/")[2]
    api_url = f"{url_root}/api/v1/video?id={video_id}&w=1920&h=1080&r={url_root}"

    headers = {"Referer": url_root}

    r = get_scraper().get(api_url, headers=headers, impersonate="chrome", timeout=10)
    r.raise_for_status()

    hex_data = r.text.strip()
    if hex_data.startswith('"') and hex_data.endswith('"'):
        hex_data = hex_data[1:-1]

    decrypted = _decrypt_data(hex_data)

    data = json.loads(decrypted)
    source = data.get("source")
    return source


def get_hls_link_uqload(url: str, headers: dict, config: dict = None) -> str | None:
    """Extract HLS link from uqload players.

    uqload serves the same XUpload/jwplayer templates as the rest of the
    family now (packed ``sources:[{file:...}]`` or the legacy
    ``sources: ["..."]`` form), so this delegates to the default extractor,
    which also retries an allowlisted Referer when the embed is restricted.
    """
    return get_hls_link_default(url, headers, config)


def get_hls_link_sendvid(url: str, headers: dict = None, config: dict = None) -> str:
    """
    Extract video link from sendvid using Open Graph meta tag.

    Args:
        url: Player URL

    Returns:
        Video URL
    """
    response = get_scraper().get(url, impersonate="chrome")
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")

    link: str = soup.find("meta", {"property": "og:video"}).attrs["content"]

    return link


def get_hls_link_sibnet(url: str, headers: dict = None, config: dict = None) -> str:
    """
    Extract video link from sibnet.

    Args:
        url: Player URL

    Returns:
        Video URL
    """
    response = get_scraper().get(url, impersonate="chrome")
    response.raise_for_status()

    relative_path = response.text.split('player.src([{src: "')[1].split('"')[0]
    link = "https://video.sibnet.ru" + relative_path

    return link


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
    req_headers.setdefault("User-Agent", DEFAULT_SCRAPER_UA)
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


def get_hls_link_vidoza(url: str, headers: dict, config: dict = None) -> str:
    """
    Extract HLS link from vidoza players.

    Args:
        url: Player URL
        headers: HTTP headers for the request

    Returns:
        HLS stream URL
    """

    response = get_scraper().get(
        url,
        headers=headers,
        impersonate="chrome",
    )
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")

    link: str = soup.find("source").attrs["src"]

    return link


def get_hls_link_kakaflix(url: str, headers: dict, config: dict = None) -> str:
    """
    Extract HLS link from kakaflix players.

    Args:
        url: Player URL
        headers: HTTP headers for the request

    Returns:
        HLS stream URL
    """
    response = get_scraper().get(
        url,
        headers=headers,
        impersonate="chrome",
    )
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")

    try:
        link: str = soup.find("iframe").attrs["src"]
    except:
        return get_hls_link(response.url, headers)
    else:
        return get_hls_link(link, headers)


def get_hls_link_myvidplay(url: str, headers: dict, config: dict = None) -> str:
    """
    Extract HLS link from myvidplay players.

    Args:
        url: Player URL
        headers: HTTP headers for the request

    Returns:
        HLS stream URL
    """
    response = get_scraper().get(
        url,
        headers=headers,
        impersonate="chrome",
    )
    response.raise_for_status()

    link = response.text.split("vtt: '")[1].split("'")[0]

    return link


def get_hls_link_vidmoly(url: str, headers: dict, config: dict = None) -> str:
    """
    Dedicated parser for Vidmoly to bypass transitional page.
    Mimics an iframe request behavior.
    """
    # Specific headers observed in browser iframe test
    vidmoly_headers = {
        "Sec-Fetch-Dest": "iframe",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "cross-site",
        "Upgrade-Insecure-Requests": "1",
        # Explicitly removing Referer as data: URL worked without it
        "Referer": "",
    }

    # Merge but prioritize our specific headers
    final_headers = {**headers, **vidmoly_headers}
    # Ensure Referer is actually removed if we mapped it to empty string/None
    if "Referer" in final_headers and not final_headers["Referer"]:
        del final_headers["Referer"]

    response = get_scraper().get(
        url,
        headers=final_headers,
        impersonate="chrome",
    )
    response.raise_for_status()

    return extract_hls_url(response.text)


def get_hls_link_veev(url, headers: dict = None, config: dict = None):
    """
    Extract HLS link from Veev players.
    Converted from https://github.com/phisher98/cloudstream-extensions-phisher/blob/master/Coflix/src/main/kotlin/com/Coflix/Extractor.kt

    Args:
        url: Player URL

    Returns:
        HLS stream URL or None if extraction fails
    """

    # 1. Extract Media ID
    media_id_match = re.search(
        r"(?://|\.)(?:veev|kinoger|poophq|doods)\.(?:to|pw|com)/[ed]/([0-9A-Za-z]+)",
        url,
    )
    if not media_id_match:
        return None
    media_id = media_id_match.group(1)

    # 2. Fetch HTML
    try:
        html = get_scraper().get(f"https://veev.to/e/{media_id}", impersonate="chrome").text
    except Exception as e:
        print(f"Connection error: {e}")
        return None

    # 3. Extract encrypted tokens
    enc_regex = r"""[.\s'](?:fc|_vvto\[[^]]*)(?:['\]]*)?\s*[:=]\s*['"]([^'"]+)"""
    found_values = re.findall(enc_regex, html)
    if not found_values:
        return None

    # --- Internal helper functions ---
    def veev_decode(etext):
        # LZW-style decompression algorithm
        lut = {i: chr(i) for i in range(256)}
        n = 256
        c = etext[0]
        result = [c]
        for char in etext[1:]:
            code = ord(char)
            entry = lut[code] if code in lut else c + c[0]
            result.append(entry)
            lut[n] = c + entry[0]
            n += 1
            c = entry
        return "".join(result)

    def parse_rules(encoded):
        # We only take the first "row" of rules, matching Kotlin's buildArray(ch)[0]
        it = iter(encoded)

        def next_int():
            try:
                char = next(it)
                return int(char) if char.isdigit() else 0
            except StopIteration:
                return 0

        count = next_int()
        if count == 0:
            return []
        row = [next_int() for _ in range(count)]
        return row[::-1]  # Reversed as in the Kotlin code

    def decode_final(encoded, rules):
        text = encoded
        for r in rules:
            if r == 1:
                text = text[::-1]  # Reverse string
            try:
                # Hex to Bytes to UTF-8
                text = bytes.fromhex(text).decode("utf-8")
            except ValueError:
                pass  # Avoid crash if hex is invalid
            text = text.replace("dXRmOA==", "")  # Remove salt
        return text

    # 4. Main loop
    for f in reversed(found_values):
        ch = veev_decode(f)
        if ch == f:
            continue  # If decoding didn't change anything, skip

        # API call to get JSON
        dl_url = f"https://veev.to/dl?op=player_api&cmd=gi&file_code={media_id}&r=https://veev.to&ch={ch}&ie=1"
        try:
            resp = get_scraper().get(dl_url, impersonate="chrome").json()
        except:
            continue

        file_obj = resp.get("file")
        if not isinstance(file_obj, dict) or file_obj.get("file_status") != "OK":
            continue

        # Kotlin equivalent: file.getJSONArray("dv")
        dv_list = file_obj.get("dv")

        # Verify it is indeed a list and not empty
        if not dv_list or not isinstance(dv_list, list):
            continue

        # Kotlin equivalent: .getJSONObject(0).getString("s")
        dv_string = dv_list[0].get("s")

        if not dv_string:
            continue

        # Final decoding steps
        step1 = veev_decode(dv_string)
        rules = parse_rules(ch)  # Rules come from 'ch'
        final_link = decode_final(step1, rules)

        return final_link

    return None


def get_hls_link_xtremestream(url, headers, config: dict = None):
    data_id = url.split("?data=")[1]
    url_root = url.removeprefix("https://").removesuffix("http://").split("/")[0]

    return f"https://{url_root}/player/xs1.php?data={data_id}"

def get_hls_link_montmyoboky(url, headers, config: dict = None):
    if "movie" in url:
        response = get_scraper().post(url=arkanime.website_origin + "/api/watch/movie-token", data={
            "movieId": url.split(":")[1]
        }, headers=headers)
        response.raise_for_status()
    else:
        response = get_scraper().post(url=arkanime.website_origin + "/api/watch/token", data={
            "episodeId": url.split(":")[1]
        }, headers=headers)
        response.raise_for_status()

    content_data = response.json()

    response_player = get_scraper().get(f'{arkanime.website_origin}/api/source/resolve?token={content_data["token"]}', headers=headers)
    response_player.raise_for_status()

    player_data = response_player.json()

    subtitle_url = player_data.get("subtitleUrl")

    return player_data["videoUrl"], subtitle_url

def get_hls_link_vidzy(embed_url: str, headers: dict, config: dict = None) -> str | None:
    """Legacy alias: Vidzy now uses the shared XUpload extractor."""
    return get_hls_link_xupload(embed_url, headers, config)


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
    req_headers.setdefault(
        "User-Agent",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36",
    )

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


# Player type -> extractor function registry.
# Adding a new player type = write one extractor here (signature:
# extractor(url: str, headers: dict, config: dict)) + add one entry below
# (and set its "type" in the player config).
PLAYER_EXTRACTORS = {
    "default": get_hls_link_default,
    "sendvid": get_hls_link_sendvid,
    "sibnet": get_hls_link_sibnet,
    "uqload": get_hls_link_uqload,
    "vidoza": get_hls_link_vidoza,
    "filemoon": get_hls_link_filemoon,
    "kakaflix": get_hls_link_kakaflix,
    "myvidplay": get_hls_link_myvidplay,
    "vidmoly": get_hls_link_vidmoly,
    "embed4me": get_hls_link_embed4me,
    "veev": get_hls_link_veev,
    "xtremestream": get_hls_link_xtremestream,
    "montmyoboky": get_hls_link_montmyoboky,
    "vidzy": get_hls_link_vidzy,
    "xupload": get_hls_link_xupload,
    "voe": get_hls_link_voe,
}


def get_hls_link(url: str, headers: dict = {}, return_subs: bool = False) -> str | tuple[str | None, str | None] | None:
    """
    Extract HLS/video link from a player URL.
    Automatically detects the player type and uses the appropriate parser.

    Args:
        url: Player URL
        headers: HTTP headers for the request (default: {})
        return_subs: Whether to also return the subtitle URL if available

    Returns:
        HLS/video stream URL if successful, None otherwise. If return_subs is True, returns (stream_url, subtitle_url).
    """

    # Find matching player and parse accordingly
    for player_name, config in players.items():
        if player_name in url.lower():
            parse_type = config["type"]
            extractor = PLAYER_EXTRACTORS.get(parse_type)

            if extractor is None:
                print_warning(
                    f"Player type '{parse_type}' is not supported in your version. "
                    "Please update: pip install --upgrade autoflix-cli"
                )
                if return_subs:
                    return None, None
                return None

            result = extractor(url, headers, config)

            if isinstance(result, tuple):
                stream_url, subtitle_url = result
            else:
                stream_url = result
                subtitle_url = None

            if return_subs:
                return stream_url, subtitle_url
            return stream_url

    if return_subs:
        return None, None
    return None


def is_supported(url: str) -> bool:
    """
    Check if a player URL is supported.

    Args:
        url: Player URL to check

    Returns:
        True if the player is supported, False otherwise
    """
    url_lower = url.lower()

    if "kakaflix" in url_lower:
        return any(kp in url_lower for kp in kakaflix_players.keys())

    return any(player in url_lower for player in players.keys())


def match_player_config(url: str) -> tuple:
    """Find the embed configuration matching the player host of an URL.

    Returns ``(config, embed_name)``, both empty when nothing matches.
    """
    for embed_name, config in players.items():
        if embed_name in url.lower():
            return config, embed_name
    return {}, ""


def test_all_scrapers_verbose(url: str, headers: dict = {}) -> dict[str, dict]:
    """
    Test all scrapers with timing and error details.

    Args:
        url: Player URL to test
        headers: HTTP headers for the request (default: {})

    Returns:
        dict mapping scraper name -> {"ok": bool, "stream_url": str | None,
        "error": str | None, "elapsed": float}
    """
    results: dict[str, dict] = {}
    for name, extractor in PLAYER_EXTRACTORS.items():
        started = time.monotonic()
        try:
            result = extractor(url, headers, {})
            elapsed = time.monotonic() - started
            stream_url = result[0] if isinstance(result, tuple) else result
            if stream_url:
                results[name] = {
                    "ok": True,
                    "stream_url": stream_url,
                    "error": None,
                    "elapsed": elapsed,
                }
            else:
                results[name] = {
                    "ok": False,
                    "stream_url": None,
                    "error": "no stream found",
                    "elapsed": elapsed,
                }
        except Exception as e:
            results[name] = {
                "ok": False,
                "stream_url": None,
                "error": f"{type(e).__name__}: {e}",
                "elapsed": time.monotonic() - started,
            }
    return results


def test_all_scrapers(url: str, headers: dict = {}) -> dict[str, str]:
    """
    Test all available scrapers on a given URL to find which ones work.

    Args:
        url: Player URL to test
        headers: HTTP headers for the request (default: {})

    Returns:
        dict mapping scraper name -> stream URL for scrapers that succeeded
    """
    return {
        name: res["stream_url"]
        for name, res in test_all_scrapers_verbose(url, headers).items()
        if res["ok"]
    }
