from curl_cffi import requests
from .deobfuscate import deobfuscate
from bs4 import BeautifulSoup
from ..proxy import curl_options
from ..config_loader import load_remote_jsonc
from ..defaults import DEFAULT_PLAYERS, DEFAULT_NEW_URL, DEFAULT_KAKAFLIX_PLAYERS

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


def get_hls_link_b(url: str, headers: dict) -> str:
    """
    Extract HLS link from type 'b' players (vidmoly, luluvdoo, etc.).

    Args:
        url: Player URL
        headers: HTTP headers for the request

    Returns:
        HLS stream URL
    """
    response = scraper.get(url, headers=headers, impersonate="chrome110")
    response.raise_for_status()

    return response.text.split('sources: [{file:"')[1].split('"')[0]


def get_hls_link_d(url: str, headers: dict) -> str:
    """
    Extract HLS link from type 'd' players.

    Args:
        url: Player URL
        headers: HTTP headers for the request

    Returns:
        HLS stream URL
    """
    response = scraper.get(url, headers=headers, impersonate="chrome110")
    response.raise_for_status()

    return response.text.split('sources: [{src: "')[1].split('"')[0]


def get_hls_link_a(url: str, headers: dict) -> str:
    """
    Extract HLS link from type 'a' players (most common type).
    Requires deobfuscation of JavaScript code.

    Args:
        url: Player URL
        headers: HTTP headers for the request

    Returns:
        HLS stream URL
    """
    response = scraper.get(url, headers=headers, impersonate="chrome110")
    response.raise_for_status()

    code = response.text.split("<script type='text/javascript'>")[1].split("\n")[0]
    code = code.removesuffix("</script>")
    code = deobfuscate(code)

    link = code.split('"hls2": "')[1].split('"')[0]

    return link


def get_hls_link_e(url: str, headers: dict) -> str:
    """
    Extract HLS link from type 'e' players.
    Requires deobfuscation of JavaScript code.

    Args:
        url: Player URL
        headers: HTTP headers for the request

    Returns:
        HLS stream URL
    """
    response = scraper.get(url, headers=headers, impersonate="chrome110")
    response.raise_for_status()

    code = response.text.split("<script type='text/javascript'>")[1].split("\n")[0]
    code = code.removesuffix("</script>")
    code = deobfuscate(code)

    link = code.split('"hls3": "')[1].split('"')[0]

    return link


def get_hls_link_c(url: str, headers: dict) -> str:
    """
    Extract HLS link from type 'c' players (ups2up).
    Requires deobfuscation of JavaScript code.

    Args:
        url: Player URL
        headers: HTTP headers for the request

    Returns:
        HLS stream URL
    """
    response = scraper.get(url, headers=headers, impersonate="chrome110")
    response.raise_for_status()

    code = response.text.split(" type='text/javascript'>")[1].split("\n")[0]
    code = code.removesuffix("</script>")
    code = deobfuscate(code)

    link = code.split('file: "')[1].split('"')[0]

    return link


def get_hls_link_f(url: str, headers: dict) -> str:
    """
    Extract HLS link from type 'f' players.
    Requires deobfuscation of JavaScript code.

    Args:
        url: Player URL
        headers: HTTP headers for the request

    Returns:
        HLS stream URL
    """
    response = scraper.get(url, headers=headers, impersonate="chrome110")
    response.raise_for_status()

    code = response.text.split("<script type='text/javascript'>")[1].split("\n")[0]
    code = code.removesuffix("</script>")
    code = deobfuscate(code)

    link = code.split('src: "')[1].split('"')[0]

    return link


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
            if parse_type == "a":
                return get_hls_link_a(url, headers)
            elif parse_type == "b":
                return get_hls_link_b(url.lower(), headers)
            elif parse_type == "c":
                return get_hls_link_c(url, headers)
            elif parse_type == "d":
                return get_hls_link_d(url, headers)
            elif parse_type == "e":
                try:
                    return get_hls_link_e(url, headers)
                except:
                    return get_hls_link_a(url, headers)
            elif parse_type == "f":
                return get_hls_link_f(url, headers)
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
