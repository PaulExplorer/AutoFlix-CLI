from bs4 import BeautifulSoup

from .common import get_scraper

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
