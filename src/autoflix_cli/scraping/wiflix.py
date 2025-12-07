import re
from bs4 import BeautifulSoup
from .objects import SearchResult, WiflixMovie, Player, WiflixSeriesSeason, Episode
from .utils import get_value_by_key, parse_episode
from ..proxy import curl_options

from curl_cffi import requests as cffi_requests

website_origin = "https://flemmix.one"

scraper = cffi_requests.Session(impersonate="chrome", curl_options=curl_options)


def search(query: str) -> list[SearchResult]:
    page_search = "/index.php?do=search"

    # Visit the homepage first to establish session/cookies (similar to the original logic)
    scraper.get(website_origin)

    data = {
        "do": "search",
        "subaction": "search",
        "story": query,
    }

    headers = {
        "Referer": f"{website_origin}/index.php?do=search",
    }

    response = scraper.post(
        website_origin + page_search,
        data=data,
        headers=headers,
        timeout=15,
    )

    if "Just a moment" in response.text:
        print("Still blocked by Cloudflare (Complex JS Challenge)")
        return []

    response.raise_for_status()

    results: list[SearchResult] = []

    soup = BeautifulSoup(response.text, "html5lib")

    for result in soup.find_all("div", {"class": "mov clearfix"}):
        title: str = result.find("a", {"class": "mov-t nowrap"}).text
        link: str = result.find("a", {"class": "mov-t nowrap"}).attrs["href"]
        img: str = website_origin + result.find("img").attrs["src"]

        genres: list[str] = []
        genres_div = result.find("div", {"class": "nbloc3"})
        if genres_div is not None:
            for genre in genres_div.find_all("a"):
                genres.append(genre.text)

        results.append(SearchResult(title, link, img, genres))

    return results


def get_movie(url: str) -> WiflixMovie:
    response = scraper.get(url)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html5lib")

    title: str = soup.find("meta", {"property": "og:title"}).attrs["content"]

    img: str = website_origin + soup.find("img", {"id": "posterimg"}).attrs["src"]
    genres: list[str] = []
    genres_div = soup.find("p", {"itemprop": "description"})
    if genres_div is not None:
        for genre in genres_div.find_all("a"):
            if "acteurs" in genre.attrs["href"]:
                continue
            genres.append(genre.text)

    info_container = soup.find("ul", {"class": "mov-list"})
    year: int = int(get_value_by_key(info_container, "Date de sortie:"))
    origin: str = get_value_by_key(info_container, "ORIGINE:")
    authors: str = get_value_by_key(info_container, "ACTEURS:")
    duration: str = get_value_by_key(info_container, "Durée:")

    players: list[Player] = []

    # Handle nested divs for player selection
    tabs_div = soup.find("div", {"class": "tabs-sel linkstab"})
    if tabs_div:
        inner_tabs = tabs_div.find("div", {"class": "tabs-sel linkstab"})
        # Fallback if the structure is slightly different
        target_div = inner_tabs if inner_tabs else tabs_div

        for player in target_div.find_all("a"):
            if "onclick" in player.attrs and "loadVideo" in player.attrs["onclick"]:
                player_url: str = (
                    player.attrs["onclick"].split("loadVideo('")[1].split("')")[0]
                )
                players.append(Player(player.text, player_url))

    return WiflixMovie(
        title, url, img, genres, year, origin, authors, duration, players
    )


def get_series_season(url: str) -> WiflixSeriesSeason:
    response = scraper.get(url)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html5lib")

    title: str = soup.find("meta", {"property": "og:title"}).attrs["content"]
    # Clean up title to remove the season part temporarily
    if soup.h1:
        title = title.removesuffix(" - " + soup.h1.text.split(" - ")[-1])
        season: str = soup.h1.text.split(" - ")[-1]
    else:
        season = "Unknown Season"

    img: str = website_origin + soup.find("img", {"id": "posterimg"}).attrs["src"]
    genres: list[str] = []
    genres_div = soup.find("p", {"itemprop": "description"})
    if genres_div is not None:
        for genre in genres_div.find_all("a"):
            if "acteurs" in genre.attrs["href"]:
                continue
            genres.append(genre.text)

    info_container = soup.find("ul", {"class": "mov-list"})
    year: int = int(get_value_by_key(info_container, "Date de sortie:"))
    origin: str = get_value_by_key(info_container, "ORIGINE:")
    authors: str = get_value_by_key(info_container, "ACTEURS:")
    duration: str = get_value_by_key(info_container, "Durée:")
    episodes: dict[str, list[Episode]] = {}

    content_div = soup.find("div", {"class": "hostsblock"})
    if content_div:
        for content in content_div.find_all("div"):
            if not content.attrs.get("class"):
                continue

            number, lang = parse_episode(content.attrs["class"][0])
            players: list[Player] = []

            for player in content.find_all("a"):
                if "onclick" in player.attrs and "loadVideo" in player.attrs["onclick"]:
                    player_url: str = (
                        player.attrs["onclick"].split("loadVideo('")[1].split("')")[0]
                    )
                    player_name: str = player.text.strip()
                    if player_url and player_name:
                        players.append(Player(player_name, player_url))

            if len(players) > 0:
                episode = Episode(f"Episode {number}", players)
                episodes[lang] = episodes.get(lang, []) + [episode]

    return WiflixSeriesSeason(
        title, season, url, img, genres, year, origin, authors, duration, episodes
    )


def get_content(url: str):
    if "film" in url.split("/")[-2]:
        return get_movie(url)
    return get_series_season(url)


if __name__ == "__main__":
    print(search("Mercredi"))
    # print(get_movie("https://flemmix.one/film-en-streaming/33832-elio-2025.html"))
    # print(
    #     get_series_season(
    #         "https://flemmix.one/vf/16375-game-of-thrones-saison-3-stmg.html"
    #     )
    # )
    # print(get_content("https://flemmix.one/film-en-streaming/33832-elio-2025.html"))
