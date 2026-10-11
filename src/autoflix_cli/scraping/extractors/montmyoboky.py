from .. import arkanime

from .common import get_scraper

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
