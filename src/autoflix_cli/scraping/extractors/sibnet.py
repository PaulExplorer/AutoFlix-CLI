from .common import get_scraper

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
