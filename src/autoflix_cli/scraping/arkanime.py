from autoflix_cli.scraping.objects import ArkSeries, Player, ArkSeason, ArkMovie
from curl_cffi import requests as cffi_requests
from .objects import SearchResult, SamaSeries, Episode
from ..proxy import DNS_OPTIONS

website_origin = ""

scraper = cffi_requests.Session(impersonate="chrome", curl_options=DNS_OPTIONS)

from .config import portals


def get_website_url(portal=portals["arkanime"]):
    global website_origin

    website_origin = portal


def search(query: str) -> list[SearchResult]:
    page = website_origin + f"/api/anime?q={query}"

    response = scraper.get(page)
    response.raise_for_status()

    results: list[SearchResult] = []

    for result in response.json()["results"]:
        title =  result["titleEnglish"]
        url = str(result["id"])
        img = result["coverImage"]
        genres = result["genres"]

        results.append(SearchResult(title, url, img, genres))

    return results

def get_content(url: str):
    response = scraper.get(website_origin + "/api/anime/" + url)
    response.raise_for_status()

    content = response.json()["result"]

    title = content["titleEnglish"]
    img = content["coverImage"]
    genres = content["genres"]

    if content["seasons"]:
        seasons:list[ArkSeason] = []
        for season in content["seasons"]:
            id = season["id"]
            season_title = season["title"]
            
            episodes: list[Episode] = []
            if season["episodes"]:
                for episode in season["episodes"]:
                    players = [
                        Player("montmyoboky (default)", "montmyoboky:" + str(episode["id"]))
                    ]

                    episodes.append(Episode(f"Episode {episode['number']} : " + episode["title"], players=players))

            elif season["arcs"]:
                for arc in season["arcs"]:
                    arc_url = website_origin + f"/api/anime/{url}/seasons/{id}/episodes?from={arc['episodeStart']}&to={arc['episodeEnd']}"
                    arc_response = scraper.get(arc_url)
                    arc_response.raise_for_status()

                    arc_json = arc_response.json()
                    for episode in arc_json["episodes"]:
                        players = [
                            Player("montmyoboky (default)", "montmyoboky:" + str(episode["id"]))
                        ]

                        episodes.append(Episode(f"Episode {episode['number']} : " + episode["title"], players=players))

            seasons.append(ArkSeason(id, season_title, episodes))

        return ArkSeries(id=url, title=title, img=img, genres=genres, seasons=seasons)
    
    elif content["movie"]:
        players = [
            Player("montmyoboky (default)", "montmyoboky_movie:" + str(content["movie"]["id"]))
        ]

        return ArkMovie(id=url, title=title, img=img, genres=genres, players=players)



if __name__ == "__main__":
    #print(search("one piece"))
    #print(get_series("106"))
    print(get_content("313"))

