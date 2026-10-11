from .common import get_scraper

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
