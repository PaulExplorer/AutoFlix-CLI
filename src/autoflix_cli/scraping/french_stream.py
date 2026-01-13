from bs4 import BeautifulSoup
from .objects import (
    SearchResult,
    FrenchStreamMovie,
    Player,
    FrenchStreamSeason,
    Episode,
)

from curl_cffi import requests as cffi_requests
from ..proxy import DNS_OPTIONS

website_origin = "https://french-stream.one"

scraper = cffi_requests.Session(impersonate="chrome", curl_options=DNS_OPTIONS)


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
        except AttributeError:
            break  # no results

        link: str = (
            website_origin
            + result.attrs["onclick"].split("location.href='")[1].split("'")[0]
        )
        try:
            img: str = website_origin + result.find("img").attrs["src"]
        except AttributeError:
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
    except AttributeError:
        img: str = ""
    genres: list[str] = []
    genres_div = soup.find("ul", {"id": "s-list"}).find_all("li")[1]
    if genres_div is not None:
        for genre in genres_div.find_all("a"):
            if genre.text:
                genres.append(genre.text)

    players: list[Player] = []

    # Handle nested divs for player selection
    filmDataDiv = soup.find("div", {"id": "film-data"})
    for key, value in filmDataDiv.attrs.items():
        if "https" in value and "affiche" not in key:
            players.append(Player(key.replace("data-", ""), value))

    return FrenchStreamMovie(title, url, img, genres, players)


def get_series_season(url: str, content: str) -> FrenchStreamSeason:
    soup = BeautifulSoup(content, "html5lib")

    title: str = soup.find("meta", {"property": "og:title"}).attrs["content"]

    episodes: dict[str, list[Episode]] = {}

    voEpisodesDiv = soup.find("div", {"id": "episodes-vo-data"})
    vostfrEpisodesDiv = soup.find("div", {"id": "episodes-vostfr-data"})
    vfEpisodesDiv = soup.find("div", {"id": "episodes-vf-data"})

    if voEpisodesDiv:
        voEpisodes = get_episodes_from_div(voEpisodesDiv)
        if voEpisodes:
            episodes["vo"] = voEpisodes
    if vostfrEpisodesDiv:
        vostfrEpisodes = get_episodes_from_div(vostfrEpisodesDiv)
        if vostfrEpisodes:
            episodes["vostfr"] = vostfrEpisodes
    if vfEpisodesDiv:
        vfEpisodes = get_episodes_from_div(vfEpisodesDiv)
        if vfEpisodes:
            episodes["vf"] = vfEpisodes

    return FrenchStreamSeason(title, url, episodes)


def get_episodes_from_div(div):
    episodes: list[Episode] = []
    for episode in div.find_all("div"):
        players = []
        for key, value in episode.attrs.items():
            if "https" in value:
                players.append(Player(key.replace("data-", ""), value))
        if players:
            episodes.append(Episode(f"Episode {episode.attrs["data-ep"]}", players))

    return episodes


def get_content(url: str):
    response = scraper.get(url)
    response.raise_for_status()
    content = response.text

    if '"episodes-' in content:
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
