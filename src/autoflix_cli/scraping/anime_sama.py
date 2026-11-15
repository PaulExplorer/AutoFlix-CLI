import time
from random import randint
from urllib.parse import urlsplit

from bs4 import BeautifulSoup
from curl_cffi import requests as cffi_requests

from ..proxy import DNS_OPTIONS
from .objects import (
    Episode,
    Player,
    SamaEpisode,
    SamaLinkContext,
    SamaSeason,
    SamaSeries,
    SearchResult,
    SeasonAccess,
)
from .utils import (
    NoEpisodesFoundError,
    parse_episodes_from_js,
    parse_season_page,
)

website_origin = ""

scraper = cffi_requests.Session(impersonate="chrome", curl_options=DNS_OPTIONS, allow_redirects="safe")

# info_class = "mt-0.5 text-gray-300 font-medium text-xs truncate"
info_class = "info-value"


from .config import portals


def get_website_url(portal=portals["anime-sama"]):
    global website_origin

    if website_origin:
        return

    if portal.startswith("http"):
        response = scraper.get(portal)
    else:
        response = scraper.get("https://" + portal)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html5lib")

    recommanded_url = soup.find("a", {"class": "btn-primary"}).attrs["href"]

    response = scraper.head(recommanded_url)
    response.raise_for_status()

    website_origin = response.url


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
            is_scan_only = True
            for type_badge in result.find_all("span", {"class": "as-badge"}):
                if type_badge.text != "Scans":
                    is_scan_only = False
                    break
            if is_scan_only:
                continue

            url: str = result.find("a").attrs["href"]
            img: str = result.find("a").img.attrs["src"]
            title: str = result.h3.text
            # genres: list[str] = info_block.find("p", {"class": info_class}).text.split(
            #     ", "
            # )
            results.append(SearchResult(title, url, img, []))

    return results


lang_codes = ["vostfr", "vf", "vj", "vcn", "vqc", "vkr", "va", "vf1", "vf2"]


def _language_url(url: str, lang: str) -> str:
    """Return ``url`` with its trailing language segment replaced by ``lang``."""
    base = url.rstrip("/")
    head, separator, last = base.rpartition("/")
    if separator and last.lower() in lang_codes:
        return f"{head}/{lang}"
    return f"{base}/{lang}"


def _url_language(url: str) -> str | None:
    """Return the language code ending ``url``, if any."""
    last = url.rstrip("/").rsplit("/", 1)[-1].lower()
    return last if last in lang_codes else None


def _api_origin(referer: str) -> str:
    if website_origin:
        return website_origin.rstrip("/")
    parts = urlsplit(referer)
    return f"{parts.scheme}://{parts.netloc}"


def _request_link(jeton: str, link_id: str, referer: str) -> tuple[str | None, str | None]:
    """Ask ``/api/lien.php`` for one link, retrying the rate limit.

    The endpoint rejects requests whose ``Sec-Fetch-Site`` is not
    ``same-origin`` (``{"erreur": "origine"}``), and answers
    ``429 {"erreur": "trop"}`` when too many links are requested at once.
    """
    error = None
    for delay in (0, 1, 3):
        if delay:
            time.sleep(delay)
        try:
            response = scraper.get(
                _api_origin(referer) + "/api/lien.php",
                params={"j": jeton, "l": link_id},
                headers={
                    "Referer": referer,
                    "Sec-Fetch-Site": "same-origin",
                },
            )
        except Exception:
            error = "reseau"
            continue

        try:
            data = response.json()
        except ValueError:
            data = {}

        if response.status_code == 200 and data.get("u"):
            return data["u"], None

        error = data.get("erreur") or f"http {response.status_code}"
        if response.status_code != 429 and error != "trop":
            return None, error

    return None, error


def _refresh_jeton(context: SamaLinkContext) -> bool:
    """Reload the season page to get a fresh API token."""
    try:
        response = scraper.get(context.referer)
        response.raise_for_status()
    except Exception:
        return False

    page = parse_season_page(response.text)
    if page is None or not page.jeton:
        return False

    context.jeton = page.jeton
    return True


def _resolve_link(raw: str, context: SamaLinkContext | None) -> str | None:
    """Resolve one ``lien:<id>`` entry to its embed URL."""
    if context is None:
        return None

    if raw.startswith("lien:"):
        link_id = raw.split(":", 1)[1]
    else:
        link_id = raw

    if not link_id:
        return None

    for attempt in range(2):
        url, error = _request_link(context.jeton, link_id, context.referer)
        if url:
            return url
        if error in ("jeton", "expire") and attempt == 0:
            if _refresh_jeton(context):
                continue
        break

    return None


def resolve_players(episode: SamaEpisode) -> list[Player]:
    """Resolve the embed URLs of one episode, caching them on the episode.

    Only the selected episode is resolved: each player costs one call to
    ``/api/lien.php`` and the endpoint rate-limits mass requests.
    """
    if episode.players:
        return episode.players

    players: list[Player] = []
    seen: set[str] = set()

    for index, raw in enumerate(episode.links or []):
        if not raw:
            continue

        if raw.startswith(("http://", "https://")):
            url = raw
        else:
            url = _resolve_link(raw, episode.link_context)

        if not url or url in seen:
            continue

        seen.add(url)
        players.append(Player(f"Lecteur {index + 1}", url))

    episode.players = players
    return players


def _parse_legacy_episodes(url: str) -> list[Episode]:
    """Fetch the former ``episodes.js`` file, for mirrors that still use it."""
    nurl = url.removesuffix("/") + f"/episodes.js?filever={randint(1, 100000)}"
    try:
        response = scraper.get(nurl, headers={"Referer": url})
    except Exception:
        return []

    if response.status_code == 404:
        return []

    try:
        response.raise_for_status()
        return parse_episodes_from_js(response.text)
    except Exception:
        return []


def _episodes_from_page(
    html: str, page_url: str, resolve_links: bool
) -> list[Episode]:
    """Build the episodes of one language page."""
    data = parse_season_page(html)

    if data is not None and data.episodes:
        has_links = any(any(link for link in links) for links in data.episodes)
        if not has_links:
            return []

        context = SamaLinkContext(referer=page_url, jeton=data.jeton)
        episodes: list[Episode] = [
            SamaEpisode(
                title=f"Épisode {index + 1}",
                players=[],
                links=links,
                link_context=context,
            )
            for index, links in enumerate(data.episodes)
        ]
    else:
        episodes = _parse_legacy_episodes(page_url)
        if not episodes:
            return []

    if resolve_links:
        for episode in episodes:
            resolve_players(episode)

    return episodes


def _fetch_language(url: str, resolve_links: bool) -> list[Episode]:
    response = scraper.get(url)
    if response.status_code == 404:
        return []
    response.raise_for_status()

    return _episodes_from_page(response.text, response.url or url, resolve_links)


def get_season(url: str, resolve_links: bool = True) -> SamaSeason:
    """Load an Anime-Sama season, one entry per available language.

    The episode list lives in the season page and only references links
    (``lien:<id>``). ``resolve_links=False`` keeps those references so the
    caller can resolve just the selected episode through
    :func:`resolve_players`; the default resolves every episode for API
    consumers that expect ready-to-use player URLs.
    """
    response = scraper.get(url)
    response.raise_for_status()
    page_url = response.url or url
    page_data = parse_season_page(response.text)

    current_lang = _url_language(url)
    langs = list(page_data.langs) if page_data else []
    if current_lang and current_lang not in langs:
        langs.insert(0, current_lang)
    if not langs:
        langs = [current_lang] if current_lang else list(lang_codes)

    episodes: dict[str, list[Episode]] = {}
    page_used = False

    for index, lang_code in enumerate(langs):
        if lang_code == current_lang or (current_lang is None and index == 0 and not page_used):
            # Reuse the page already fetched instead of requesting it twice.
            lang_episodes = _episodes_from_page(
                response.text, page_url, resolve_links
            )
            page_used = True
        else:
            lang_episodes = _fetch_language(
                _language_url(url, lang_code), resolve_links
            )

        if lang_episodes:
            episodes[lang_code] = lang_episodes

    if not episodes:
        # The catalogue entry exists but the content has no playable link,
        # i.e. it is probably not released yet.
        raise NoEpisodesFoundError()

    # Clean up the title based on the URL
    parts = url.removesuffix("/").split("/")
    # Take the second to last element if the url ends with the language, otherwise adjust according to structure
    name = parts[-2].title() if len(parts) >= 2 else "Unknown"

    num = "0123456789"
    for char in num:
        name = name.replace(char, " " + char)

    return SamaSeason(name, url, list(episodes.keys()), episodes)


# season_container_class = "flex flex-wrap overflow-y-hidden justify-start bg-slate-900 bg-opacity-70 rounded mt-2 h-auto"
def get_series(url: str) -> SamaSeries:
    response = scraper.get(url)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html5lib")

    title: str = soup.h1.text

    img_container = soup.find("img", {"id": "coverOeuvre"})
    if img_container is None:
        # Current layout: poster in the hero, wide backdrop as a fallback.
        img_container = soup.select_one(".oe-affiche img") or soup.select_one(
            ".oe-fond img"
        )

    if img_container:
        img: str = img_container.attrs.get("src")
        if img and img.startswith("/"):
            img = website_origin.rstrip("/") + img
    else:
        img: str = None

    genres: list[str] = []

    genres_div = soup.find("div", {"class": "oe-genres"})
    if genres_div:
        for genre in genres_div.select("span, a.genre-pill"):
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
