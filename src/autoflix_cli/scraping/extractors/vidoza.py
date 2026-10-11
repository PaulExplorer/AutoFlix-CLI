from bs4 import BeautifulSoup

from .common import get_scraper

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
