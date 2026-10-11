from bs4 import BeautifulSoup

from .common import get_scraper

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

    from ..player import get_hls_link  # deferred: dispatcher owns the registry

    soup = BeautifulSoup(response.text, "html.parser")

    try:
        link: str = soup.find("iframe").attrs["src"]
    except:
        return get_hls_link(response.url, headers)
    else:
        return get_hls_link(link, headers)
