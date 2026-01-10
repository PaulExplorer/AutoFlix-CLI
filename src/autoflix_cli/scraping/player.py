from curl_cffi import requests
from .deobfuscate import deobfuscate
from bs4 import BeautifulSoup
from ..proxy import curl_options
from ..config_loader import load_remote_jsonc
from ..defaults import DEFAULT_PLAYERS, DEFAULT_NEW_URL, DEFAULT_KAKAFLIX_PLAYERS
import re

scraper = requests.Session(curl_options=curl_options)

# Player mapping: domain name -> parser type
# Player mapping and configuration
players = load_remote_jsonc(
    "https://raw.githubusercontent.com/PaulExplorer/AutoFlix-CLI/refs/heads/main/data/players_info.jsonc",
    DEFAULT_PLAYERS,
)

# URL replacements for compatibility
new_url = load_remote_jsonc(
    "https://raw.githubusercontent.com/PaulExplorer/AutoFlix-CLI/refs/heads/main/data/new_url.jsonc",
    DEFAULT_NEW_URL,
)

# kakaflix supported players
kakaflix_players = load_remote_jsonc(
    "https://raw.githubusercontent.com/PaulExplorer/AutoFlix-CLI/refs/heads/main/data/kakaflix_players.jsonc",
    DEFAULT_KAKAFLIX_PLAYERS,
)


def extract_hls_url(unpacked_code):
    pattern = r'["\'](https?://[^"\']*master\.txt[^"\']*)["\']'
    match = re.search(pattern, unpacked_code)
    if match:
        return match.group(1)

    pattern = r'["\'](https?://[^"\']*master\.m3u8[^"\']*)["\']'
    match = re.search(pattern, unpacked_code)
    if match:
        return match.group(1)

    return None


def get_hls_link_default(url: str, headers: dict) -> str:
    response = scraper.get(url, headers=headers, impersonate="chrome110")
    response.raise_for_status()

    code = deobfuscate(response.text)

    return extract_hls_url(code)


def get_hls_link_uqload(url: str, headers: dict) -> str:
    """
    Extract HLS link from uqload players.

    Args:
        url: Player URL
        headers: HTTP headers for the request

    Returns:
        HLS stream URL
    """
    response = scraper.get(
        url.replace("embed-", ""),
        headers={**headers, "Referer": "https://uqload.cx/"},
        impersonate="chrome110",
    )
    response.raise_for_status()

    link = response.text.split('sources: ["')[1].split('"')[0]

    return link


def get_hls_link_sendvid(url: str) -> str:
    """
    Extract video link from sendvid using Open Graph meta tag.

    Args:
        url: Player URL

    Returns:
        Video URL
    """
    response = scraper.get(url, impersonate="chrome110")
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")

    link: str = soup.find("meta", {"property": "og:video"}).attrs["content"]

    return link


def get_hls_link_sibnet(url: str) -> str:
    """
    Extract video link from sibnet.

    Args:
        url: Player URL

    Returns:
        Video URL
    """
    response = scraper.get(url, impersonate="chrome110")
    response.raise_for_status()

    relative_path = response.text.split('player.src([{src: "')[1].split('"')[0]
    link = "https://video.sibnet.ru" + relative_path

    return link


def get_hls_link_filemoon(url: str, headers: dict) -> str:
    """
    Extract HLS link from filemoon players.
    Follows iframe redirect and deobfuscates JavaScript.

    Args:
        url: Player URL

    Returns:
        HLS stream URL
    """
    response = scraper.get(
        url,
        headers={
            **headers,
            "Sec-Fetch-Dest": "iframe",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "cross-site",
        },
        impersonate="chrome110",
    )
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")

    link: str = soup.find("iframe").attrs["src"]

    response = scraper.get(link, impersonate="chrome110")
    response.raise_for_status()

    code = response.text.split("<script data-cfasync='false' type='text/javascript'>")[
        1
    ].split("\n")[0]
    code = code.removesuffix("</script>")
    code = deobfuscate(code)

    link = code.split('file: "')[1].split('"')[0]

    return link


def get_hls_link_vidoza(url: str, headers: dict) -> str:
    """
    Extract HLS link from vidoza players.

    Args:
        url: Player URL
        headers: HTTP headers for the request

    Returns:
        HLS stream URL
    """

    response = scraper.get(
        url,
        headers=headers,
        impersonate="chrome110",
    )
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")

    link: str = soup.find("source").attrs["src"]

    return link


def get_hls_link_kakaflix(url: str, headers: dict) -> str:
    """
    Extract HLS link from kakaflix players.

    Args:
        url: Player URL
        headers: HTTP headers for the request

    Returns:
        HLS stream URL
    """
    response = scraper.get(
        url,
        headers=headers,
        impersonate="chrome110",
    )
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")

    try:
        link: str = soup.find("iframe").attrs["src"]
    except:
        return get_hls_link(response.url, headers)
    else:
        return get_hls_link(link, headers)


def get_hls_link_myvidplay(url: str, headers: dict) -> str:
    """
    Extract HLS link from myvidplay players.

    Args:
        url: Player URL
        headers: HTTP headers for the request

    Returns:
        HLS stream URL
    """
    response = scraper.get(
        url,
        headers=headers,
        impersonate="chrome110",
    )
    response.raise_for_status()

    link = response.text.split("vtt: '")[1].split("'")[0]

    return link


def get_hls_link_vidmoly(url: str, headers: dict) -> str:
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

    response = scraper.get(
        url,
        headers=final_headers,
        impersonate="chrome110",
    )
    response.raise_for_status()

    return response.text.split('sources: [{file:"')[1].split('"')[0]


def get_hls_link(url: str, headers: dict = {}) -> str | None:
    """
    Extract HLS/video link from a player URL.
    Automatically detects the player type and uses the appropriate parser.

    Args:
        url: Player URL
        headers: HTTP headers for the request (default: {})

    Returns:
        HLS/video stream URL if successful, None otherwise
    """

    # Find matching player and parse accordingly
    for player_name, config in players.items():
        if player_name in url.lower():
            parse_type = config["type"]
            if parse_type == "default":
                return get_hls_link_default(url, headers)
            elif parse_type == "sendvid":
                return get_hls_link_sendvid(url)
            elif parse_type == "sibnet":
                return get_hls_link_sibnet(url)
            elif parse_type == "uqload":
                return get_hls_link_uqload(url, headers)
            elif parse_type == "vidoza":
                return get_hls_link_vidoza(url, headers)
            elif parse_type == "filemoon":
                return get_hls_link_filemoon(url, headers)
            elif parse_type == "kakaflix":
                return get_hls_link_kakaflix(url, headers)
            elif parse_type == "myvidplay":
                return get_hls_link_myvidplay(url, headers)
            elif parse_type == "vidmoly":
                return get_hls_link_vidmoly(url, headers)

    return None


def is_supported(url: str) -> bool:
    """
    Check if a player URL is supported.

    Args:
        url: Player URL to check

    Returns:
        True if the player is supported, False otherwise
    """
    for player in players.keys():
        if "kakaflix" in url.lower():
            for player in kakaflix_players.keys():
                if player in url.lower():
                    return True
            return False

        elif player in url.lower():
            return True

    return False
