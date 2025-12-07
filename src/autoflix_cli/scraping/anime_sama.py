from curl_cffi import requests as cffi_requests
from bs4 import BeautifulSoup
from .objects import SearchResult, SamaSeason, SamaSeries, SeasonAccess, Episode
from .utils import parse_episodes_from_js
from ..proxy import curl_options

website_origin = "https://anime-sama.eu"

scraper = cffi_requests.Session(impersonate="chrome", curl_options=curl_options)

# info_class = "mt-0.5 text-gray-300 font-medium text-xs truncate"
info_class = "info-value"


def search(query: str) -> list[SearchResult]:
    page = website_origin + f"/catalogue/?search={query}"

    response = scraper.get(page)
    response.raise_for_status()

    results: list[SearchResult] = []

    soup = BeautifulSoup(response.text, "html5lib")

    result_container = soup.find("div", {"id": "list_catalog"})

    # Check if the container exists to avoid errors if no results
    if result_container:
        for result in result_container.find_all("div", recursive=False):
            is_scan_only = False
            for info in result.find_all("p", {"class": info_class}):
                if info.text == "Scans":
                    is_scan_only = True
                    break
            if is_scan_only:
                continue

            url: str = result.find("a").attrs["href"]
            img: str = result.find("a").img.attrs["src"]
            info_block = result.find("div", {"class": "card-content"})
            title: str = info_block.h2.text
            genres: list[str] = info_block.find("p", {"class": info_class}).text.split(
                ", "
            )
            results.append(SearchResult(title, url, img, genres))

    return results


lang_codes = ["vostfr", "vf", "vj", "vcn", "vqc", "vkr", "va", "vf1", "vf2"]


def get_season(url: str) -> SamaSeason:
    episodes: dict[str, list[Episode]] = {}
    valid_lang = []
    for lang_code in lang_codes:
        nurl = url.replace("vostfr", lang_code).removesuffix("/") + "/episodes.js"
        response = scraper.get(nurl)

        if response.status_code == 404:
            continue
        response.raise_for_status()

        episodes[lang_code] = parse_episodes_from_js(response.text)
        valid_lang.append(lang_code)

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

    title: str = soup.find("h4", {"id": "titreOeuvre"}).text
    img: str = soup.find("img", {"id": "coverOeuvre"}).attrs["src"]
    genres: list[str] = soup.find("a", {"class": "text-sm text-gray-300"}).text.split(
        ", "
    )

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
