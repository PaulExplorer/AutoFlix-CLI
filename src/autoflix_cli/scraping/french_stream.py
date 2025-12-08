from bs4 import BeautifulSoup
from .objects import (
    SearchResult,
    FrenchStreamMovie,
    Player,
    FrenchStreamSeason,
    Episode,
)
from .utils import parse_dirty_json

from curl_cffi import requests as cffi_requests
from ..proxy import curl_options

website_origin = "https://french-stream.one"

scraper = cffi_requests.Session(impersonate="chrome", curl_options=curl_options)


def search(query: str) -> list[SearchResult]:
    page_search = "/engine/ajax/search.php"

    data = {
        "query": query,
        "page": 1,
    }

    headers = {
        "Referer": f"{website_origin}/",
    }

    response = scraper.post(
        website_origin + page_search,
        data=data,
        headers=headers,
        timeout=15,
    )

    response.raise_for_status()

    results: list[SearchResult] = []

    soup = BeautifulSoup(response.text, "html5lib")

    for result in soup.find_all("div", {"class": "search-item"}):
        try:
            title: str = result.find("div", {"class": "search-title"}).text
        except:
            break  # no results

        link: str = (
            website_origin
            + result.attrs["onclick"].split("location.href='")[1].split("'")[0]
        )
        try:
            img: str = website_origin + result.find("img").attrs["src"]
        except:
            img: str = ""  # no image

        genres: list[str] = []  # unknow

        results.append(SearchResult(title, link, img, genres))

    return results


def get_movie(url: str, content: str) -> FrenchStreamMovie:
    soup = BeautifulSoup(content, "html5lib")

    title: str = soup.find("meta", {"property": "og:title"}).attrs["content"]

    img: str = ""
    try:
        img: str = (
            website_origin + soup.find("img", {"class": "dvd-thumbnail"}).attrs["src"]
        )
    except:
        img: str = ""
    genres: list[str] = []
    genres_div = soup.find("ul", {"id": "s-list"}).find_all("li")[1]
    if genres_div is not None:
        for genre in genres_div.find_all("a"):
            if genre.text:
                genres.append(genre.text)

    players: list[Player] = []

    # Handle nested divs for player selection
    players_json = content.split("var playerUrls = ")[1].split(";")[0]
    players_json = parse_dirty_json(players_json)
    for player, links in players_json.items():
        if links["Default"]:
            players.append(Player(player, links["Default"]))

    return FrenchStreamMovie(title, url, img, genres, players)


def get_series_season(url: str, content: str) -> FrenchStreamSeason:
    soup = BeautifulSoup(content, "html5lib")

    title: str = soup.find("meta", {"property": "og:title"}).attrs["content"]

    episodes: dict[str, list[Episode]] = {}

    episodes_json = content.split("var episodesData = ")[1].split(";")[0]
    episodes_json = parse_dirty_json(episodes_json)

    for lang, episodes_data in episodes_json.items():
        for episode, players_data in episodes_data.items():
            players = []

            for player, link in players_data.items():
                if link:
                    players.append(Player(player, link))

            if players:
                episodes[lang] = episodes.get(lang, []) + [
                    Episode(f"Episode {episode}", players)
                ]

    return FrenchStreamSeason(title, url, episodes)


def get_content(url: str):
    response = scraper.get(url)
    response.raise_for_status()
    content = response.text

    if "episodesData" in content:
        return get_series_season(url, content)
    return get_movie(url, content)


if __name__ == "__main__":
    # print(search("Mercredi"))
    # print(
    #     get_movie(
    #         "https://french-stream.one/films/13448-la-soupe-aux-choux-film-streaming-complet-vf.html"
    #     )
    # )
    print(
        get_series_season(
            "https://french-stream.one/s-tv/15112935-mercredi-saison-1.html"
        )
    )
