from curl_cffi import requests as cffi_requests
from bs4 import BeautifulSoup
from .objects import SearchResult, SamaSeason, SamaSeries, SeasonAccess, Episode
from .utils import parse_episodes_from_js, NoEpisodesFoundError
from ..proxy import DNS_OPTIONS
from random import randint

API_URL = ""

scraper = cffi_requests.Session(
    impersonate="chrome",
    curl_options=DNS_OPTIONS,
    allow_redirects="safe",
    headers={
        "Origin": "https://franime.fr",
        "Referer": "https://franime.fr/",
    },
)

def get_website_url():
    API_URL = "https://api.franime.fr/api/"

def search(query: str) -> list[SearchResult]:
    url = "https://api.franime.fr/api/animes"
    response = scraper.get(url)
    response.raise_for_status()

    results: list[SearchResult] = []
    # ne pas tenir compte des majuscules ou espaces dans la recherche de l'utilisateur
    query = query.casefold().strip()

    for anime in response.json():
        
        # Créer une liste des différents titres principaux et secondaires
        titles = [anime.get("title", ""), anime.get("titleO", "")]
        other_titles = anime.get("titles") or {}
        titles.extend(other_titles.values())

        # si la recherche de l'utilisateur est présente dans un titre de la liste, 
        # retourner les info de l'anime correspondant dans SearchResult
        if any(query in title.casefold() for title in titles if title):
            results.append(
                SearchResult(
                      title=anime["title"],
                      id=anime["id"],
                      url="",
                      img="",
                      genres=[],
                      # pourquoi tous ces arguments sont necessaires alors que seul
                      # le titre nous interesse pour la recherche ?
                )
            )
        # fait en sorte que les animes ou les correspondances sont 
        # dans le titre principal ("title" dans l'api) apparaissent en premier
        # dans la liste
        results.sort(
           key=lambda result: query not in result.title.casefold()
        )
            
    return results


lang_codes = ["vostfr", "vf", "vj", "vcn", "vqc", "vkr", "va", "vf1", "vf2"]


def get_season(url: str) -> SamaSeason:
    episodes: dict[str, list[Episode]] = {}
    valid_lang = []
    for lang_code in lang_codes:
        nurl = (
            url.replace("vostfr", lang_code).removesuffix("/")
            + f"/episodes.js?filever={randint(1, 100000)}"
        )
        response = scraper.get(nurl, headers={
            "Referer": url.replace("vostfr", lang_code)
        })

        if response.status_code == 404:
            continue
        response.raise_for_status()

        episodes[lang_code] = parse_episodes_from_js(response.text)
        valid_lang.append(lang_code)

    if valid_lang and not any(episodes.values()):
        # Every available language parsed to an empty episode list: the
        # catalogue entry exists but the content has no playable links,
        # i.e. it is probably not released yet. Raise a clean error
        # instead of crashing later in the flow.
        raise NoEpisodesFoundError()

    # Clean up the title based on the URL
    parts = url.removesuffix("/").split("/")
    # Take the second to last element if the url ends with the language, otherwise adjust according to structure
    name = parts[-2].title() if len(parts) >= 2 else "Unknown"

    num = "0123456789"
    for char in num:
        name = name.replace(char, " " + char)

    return SamaSeason(name, url, valid_lang, episodes)


# season_container_class = "flex flex-wrap overflow-y-hidden justify-start bg-slate-900 bg-opacity-70 rounded mt-2 h-auto"
def get_series(url: str) -> SamaSeries:
    response = scraper.get(url)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html5lib")

    title: str = soup.h1.text

    img_container = soup.find("img", {"id": "coverOeuvre"})
    if img_container:
        img: str = img_container.attrs["src"]
    else:
        img: str = None

    genres: list[str] = []

    genres_div = soup.find("div", {"class": "oe-genres"})
    for genre in genres_div.find_all("span"):
        genres.append(genre.text.strip())

    seasons: list[SeasonAccess] = []

    # Using css select as in the original code
    selection = soup.css.select("div.flex.flex-wrap.overflow-y-hidden")

    if selection:
        seasons_script = selection[0].script
        if seasons_script:
            # Manual parsing of the JS script to extract seasons
            for season in str(seasons_script).split('panneauAnime("')[2:]:
                parts = season.split('"')
                if len(parts) > 2:
                    season_title = parts[0]
                    # The original logic assumes a specific JS structure
                    url_part = season.split('", "')[1].split('"')[0]
                    season_url = url + "/" + url_part
                    seasons.append(SeasonAccess(season_title, season_url))

                if season.endswith("/*"):
                    break

    return SamaSeries(title, url, img, genres, seasons)


if __name__ == "__main__":
    # print(search("one piece"))
    # print(get_series("https://anime-sama.fr/catalogue/bofuri/"))
    # print(get_season("https://anime-sama.fr/catalogue/hunter-x-hunter/saison1/vostfr/"))
    print(
        get_season(
            "https://anime-sama.fr/catalogue/le-chateau-dans-le-ciel/film/vostfr"
        )
    )
