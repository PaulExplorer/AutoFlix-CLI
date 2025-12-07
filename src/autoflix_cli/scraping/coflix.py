from curl_cffi import requests as cffi_requests
from bs4 import BeautifulSoup
from .objects import (
    SearchResult,
    CoflixSeason,
    CoflixSeries,
    SeasonAccess,
    EpisodeAccess,
    Episode,
    Player,
    CoflixMovie,
)
from .utils import parse_episodes_from_js
import base64
from ..proxy import curl_options

website_origin = "https://coflix.foo"
scraper = cffi_requests.Session(impersonate="chrome", curl_options=curl_options)


def search(query: str) -> list[SearchResult]:
    page = website_origin + f"/suggest.php?query={query}"

    response = scraper.get(page)
    response.raise_for_status()
    response = response.json()

    results: list[SearchResult] = []

    for result in response:
        image: str = result["image"]
        # Handle cases where the image might not have the expected format
        try:
            image = "https://" + image.split("//")[1].split('"')[0]
        except IndexError:
            pass  # Keep the original url if the split fails

        results.append(SearchResult(result["title"], result["url"], image, []))

    return results


def get_players(players_url: str) -> list[Player]:
    """
    Get list of players from a player URL.

    Args:
        players_url: URL to fetch players from

    Returns:
        List of Player objects
    """
    headers = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "fr-FR,en-US;q=0.7,en;q=0.3",
        "Sec-GPC": "1",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "cross-site",
        "Sec-Fetch-User": "?1",
        "Priority": "u=0, i",
        "Referer": website_origin,
    }

    response = scraper.get(players_url, headers=headers)
    response.raise_for_status()

    content = response.text
    soup = BeautifulSoup(content, "html5lib")

    players = []
    for li in soup.find_all("li"):
        if "onclick" in li.attrs and "showVideo" in li.attrs["onclick"]:
            player_name = li.find("span").text.strip()
            player_name = player_name.split(" /")[0]
            link = base64.b64decode(li.attrs["onclick"].split("'")[1].split("'")[0])
            players.append(Player(player_name, str(link, "utf-8")))

    return players


def get_episode(url: str) -> Episode:
    """
    Get episode details including players.

    Args:
        url: Episode URL

    Returns:
        Episode object with title and players
    """
    response = scraper.get(url)
    response.raise_for_status()

    content = response.text
    soup = BeautifulSoup(content, "html5lib")

    title: str = soup.find("span").text.strip()
    players_url = soup.find("iframe").attrs["src"]

    players = get_players(players_url)

    return Episode(title, players)


def get_season(url: str) -> CoflixSeason:
    response = scraper.get(url)
    response.raise_for_status()

    content = response.json()

    title = content["title"]
    episodes: list[EpisodeAccess] = []

    for episode in content["episodes"]:
        name = f"Episode {episode['number']}"
        episodes.append(EpisodeAccess(name, url=episode["links"]))

    return CoflixSeason(title, url, episodes)


def get_movie(url: str) -> CoflixMovie:
    response = scraper.get(url)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html5lib")

    title: str = soup.find("h1").text.strip()
    img: str = soup.find("div", {"class": "title-img"}).find("img").attrs["src"]

    genres: list[str] = []
    genres_container = soup.find("div", {"class": "ctgrs"})

    if genres_container:
        for genre_link in genres_container.find_all("a"):
            genres.append(genre_link.text)

    year_elem = soup.find("span", {"class": "fwb fz20 e-fz25 dib"})
    year = year_elem.text.strip() if year_elem else "Unknown"

    players_url = soup.find("iframe").attrs["src"]
    players = get_players(players_url)

    return CoflixMovie(title, url, img, genres, year, players)


def get_series(url: str) -> CoflixSeries:
    response = scraper.get(url)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html5lib")

    title: str = soup.find("h1").text.strip()
    img: str = soup.find("div", {"class": "poster"}).find("img").attrs["src"]

    genres: list[str] = []
    genres_container = soup.find("div", {"class": "ctgrs"})

    if genres_container:
        for genre_link in genres_container.find_all("a"):
            genres.append(genre_link.text)

    seasons_container = soup.find("ul", {"class": "sub-menu"})
    seasons: list[SeasonAccess] = []

    if seasons_container:
        for season in seasons_container.find_all("li"):
            input_element = season.find("input")
            if input_element:
                element_id = input_element.attrs["post-id"]
                season_id = input_element.attrs["data-season"]

                link = f"{website_origin}/wp-json/apiflix/v1/series/{element_id}/{season_id}"
                seasons.append(SeasonAccess(season.text.strip(), link))

    return CoflixSeries(title, url, img, genres, seasons)


def get_content(url: str):
    """
    Auto-detect and get content (movie or series) based on URL.

    Args:
        url: Content URL

    Returns:
        CoflixMovie if URL contains '/film/', CoflixSeries otherwise
    """
    if "/film/" in url:
        return get_movie(url)
    return get_series(url)


if __name__ == "__main__":
    # print(search("mercredi"))
    # print(get_series("https://coflix.foo/serie/game-of-thrones/"))
    # print(get_season("https://coflix.foo/wp-json/apiflix/v1/series/14261/4"))
    print(get_episode("https://coflix.foo/episode/game-of-thrones-4x9/"))
