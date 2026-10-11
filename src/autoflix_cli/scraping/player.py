"""Embed-player dispatcher: configuration, registry and public API.

Per-host extractors live in :mod:`autoflix_cli.scraping.extractors` (one
module per player ``type``). This module loads the configuration, maps embed
URLs to extractors, and re-exports the extractor functions so existing
``player.<name>`` imports keep working.
"""

import os
import time

from ..config_loader import load_config
from ..defaults import DEFAULT_PLAYERS, DEFAULT_NEW_URL, DEFAULT_KAKAFLIX_PLAYERS
from ..cli_utils import print_warning
from .extractors.common import (
    _extract_jwplayer_source,
    _extract_streamhide_links,
    _fetch_embed_page,
    _unpack_all,
    extract_hls_url,
    extract_video_url,
    get_scraper,
    scraper,
)
from .extractors.default import get_hls_link_default
from .extractors.embed4me import get_hls_link_embed4me
from .extractors.filemoon import (
    _filemoon_b64url,
    _filemoon_select_parts,
    get_hls_link_filemoon,
)
from .extractors.kakaflix import get_hls_link_kakaflix
from .extractors.montmyoboky import get_hls_link_montmyoboky
from .extractors.myvidplay import get_hls_link_myvidplay
from .extractors.sendvid import get_hls_link_sendvid
from .extractors.sibnet import get_hls_link_sibnet
from .extractors.uqload import get_hls_link_uqload
from .extractors.veev import get_hls_link_veev
from .extractors.vidmoly import get_hls_link_vidmoly
from .extractors.vidoza import get_hls_link_vidoza
from .extractors.vidzy import get_hls_link_vidzy
from .extractors.voe import _voe_b64decode, _voe_decode, get_hls_link_voe
from .extractors.xtremestream import get_hls_link_xtremestream
from .extractors.xupload import get_hls_link_xupload

__all__ = [
    "get_scraper",
    "scraper",
    "players",
    "new_url",
    "kakaflix_players",
    "PLAYER_EXTRACTORS",
    "get_hls_link",
    "is_supported",
    "match_player_config",
    "test_all_scrapers",
    "test_all_scrapers_verbose",
    "get_hls_link_default",
    "get_hls_link_embed4me",
    "get_hls_link_filemoon",
    "get_hls_link_kakaflix",
    "get_hls_link_montmyoboky",
    "get_hls_link_myvidplay",
    "get_hls_link_sendvid",
    "get_hls_link_sibnet",
    "get_hls_link_uqload",
    "get_hls_link_veev",
    "get_hls_link_vidmoly",
    "get_hls_link_vidoza",
    "get_hls_link_vidzy",
    "get_hls_link_voe",
    "get_hls_link_xtremestream",
    "get_hls_link_xupload",
    "extract_hls_url",
    "extract_video_url",
]

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


# Player type -> extractor function registry.
# Adding a new player type = write one extractor in extractors/ (signature:
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
