from curl_cffi import requests as cffi_requests
from bs4 import BeautifulSoup
from .objects import (
    SearchResult,
    CoflixSeason,
    CoflixSeries,
    EpisodeAccess,
    Episode,
    Player,
    CoflixMovie,
)
from .utils import parse_episodes_from_js
import base64
import re
from ..proxy import DNS_OPTIONS

website_origin = ""
scraper = cffi_requests.Session(impersonate="chrome", curl_options=DNS_OPTIONS)


from .config import portals


def get_website_url(portal=portals["coflix"]):
    global website_origin

    if website_origin:
        return

    if portal.startswith("http"):
        response = scraper.head(portal)
    else:
        response = scraper.head("https://" + portal)
    response.raise_for_status()

    website_origin = response.url


def search(query: str) -> list[SearchResult]:
    page = website_origin + f"/?s={query}"

    response = scraper.get(page)
    response.raise_for_status()

    content = response.text
    soup = BeautifulSoup(content, "html5lib")

    results: list[SearchResult] = []

    for result in soup.find_all("div", {"class": "md-manga-card"}):
        try:
            if result.find("img").attrs["src"]:
                image: str = "https:" + result.find("img").attrs["src"]
            else: image = None
        except: image = None

        title = result.find("p", {"class": "md-manga-card-name"}).text
        url = result.find("a").attrs["href"]

        results.append(SearchResult(title, url, image, []))

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

    title: str = soup.find("h1").text
    players_url: str = soup.find("iframe").attrs["src"]

    players = get_players(players_url)

    return Episode(title, players)

def get_genres(soup) -> list[str]:
    genres: list[str] = []
    genres_container = soup.find("div", {"class": "cf-movie-tags-row"})

    if genres_container:
        for genre_link in genres_container.find_all("a"):
            genres.append(genre_link.text)

    return genres

def get_content_img(soup) -> str:
    try:
        if soup.find("img", {"class": "cf-movie-cover-img"}).attrs["src"]:
            return soup.find("img", {"class": "cf-movie-cover-img"}).attrs["src"]
    except: pass

    return None

def get_movie(url: str) -> CoflixMovie:
    response = scraper.get(url)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html5lib")

    title: str = soup.find("h1").text.strip()
    img: str = get_content_img(soup)
    genres: list[str] = get_genres(soup)

    players_url = soup.find("iframe", {"id": "cfPlayerFrame"}).attrs["src"]
    players = get_players(players_url)

    return CoflixMovie(title, url, img, genres, players)

def get_season_name(soup, id):
    season_container = soup.find("div", {"id": "cfSeasonTabs"})

    for season in season_container.find_all("button"):
        if season.attrs["data-season"] == id:
            title = season.get_text(strip=True)
            span_text = season.find('span', class_='cf-server-tab-lang').get_text(strip=True)
            
            title = title.replace(span_text, "")
            result = f"{title} ({span_text})"

            return result

    try:
        return "Saison" + (int(id) + 1)
    except: 
        return "Saison Inconnu"

def get_series(url: str) -> CoflixSeries:
    response = scraper.get(url)
    response.raise_for_status()

    content = response.text
    soup = BeautifulSoup(content, "html5lib")

    title: str = soup.find("h1").text.strip()
    img: str = get_content_img(soup)
    genres: list[str] = get_genres(soup)

    seasons: list[CoflixSeason] = []

    for season in soup.find_all("div", {"class": "cf-episodes-panel"}):
        episodes: list[EpisodeAccess] = []
        for episode in season.find_all("div", {"class": "cf-episode-item"}):
            episode_name = episode.find("span", {"class": "cf-episode-title"}).text
            onclick = episode.attrs.get("onclick", "")
            match = re.search(r"https?://[^\s'\"<>]+", onclick)
            episode_url = match.group(0) if match else onclick

            episodes.append(EpisodeAccess(episode_name, episode_url))

        season_name = get_season_name(soup, season.attrs["data-panel"])

        seasons.append(CoflixSeason(season_name, episodes))

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
