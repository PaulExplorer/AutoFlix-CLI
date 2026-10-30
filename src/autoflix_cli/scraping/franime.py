"""Scraper for FRAnime (https://franime.fr).

Unlike Anime-Sama, FRAnime does not serve HTML pages to scrape: the whole
catalogue lives in a JSON API on ``api.franime.fr``. The flow is:

1. ``GET /api/animes`` returns every anime of the catalogue (the site itself
   loads it once and filters client-side, there is no search endpoint).
2. ``GET /api/anime-by-id/:id`` returns the seasons with their episodes and,
   per language, the list of third-party providers ("lecteurs").
3. ``GET /api/anime/:animeId/:saisonIndex/:episodeIndex/:lang/:lecteurIndex``
   returns a plain-text ``https://franime.fr/watch2/?...`` URL which encodes
   the real provider embed URL behind base64 + hex + a single-byte XOR key.
   Brute-forcing the 256 possible keys instantly decrypts it offline.
"""

import base64
import binascii
import re
import string
import time
import urllib.parse
from dataclasses import dataclass, field

from curl_cffi import requests as cffi_requests

from .objects import Player, SamaSeason, SamaSeries, SearchResult, SeasonAccess
from .utils import NoEpisodesFoundError
from ..cli_utils import print_error, print_warning
from ..proxy import DNS_OPTIONS

API_URL = "https://api.franime.fr/api/"
website_origin = "https://franime.fr"

scraper = cffi_requests.Session(
    impersonate="chrome",
    curl_options=DNS_OPTIONS,
    allow_redirects="safe",
    headers={
        "Origin": website_origin,
        "Referer": website_origin + "/",
    },
)


@dataclass
class FranimeEpisode:
    """Episode with the extras needed to resolve a player on demand.

    Resolving a provider URL costs one API call plus one decryption per
    player, so the embed URLs are only resolved for the episode the user
    actually selected. ``index`` is the 0-based position of the episode in
    the season (required by the resolver), and ``lecteurs`` maps ``"vo"``
    / ``"vf"`` to the provider names list.
    """

    title: str
    players: list[Player]
    index: int
    lecteurs: dict[str, list[str]] = field(default_factory=dict)


season_url_re = re.compile(r"/anime/(\d+)/(\d+)(?:/|$)")

# Domains the watch2 links are known to point to. Used to confirm a
# brute-forced XOR key produced a real provider URL instead of garbage.
KNOWN_PROVIDERS = [
    "sibnet.ru",
    # filemoon's website ships rotating mirror domains: the "bys<slug>".com
    # family. Any new slug decrypts through the printable-URL fallback.
    "bysedikamoum",
    "bysebuho",
    "bysekoze",
    "filemoon",
    "sendvid",
    "vidmoly",
    "streamtape",
    "doodstream",
    "uqload",
    "vidoza",
    "vidguard",
    "embedrise",
    "kiwifil",
]

# The catalogue is a single (heavy) JSON call, reused for every search.
_catalogue: list | None = None
_catalogue_loaded_at: float = 0.0
_CATALOGUE_TTL = 60 * 60  # 1 hour


def _display_title(data: dict) -> str:
    """FRAnime displays the English title, falling back to the original."""
    titles = data.get("titles") or {}
    return (
        data.get("title")
        or titles.get("en")
        or titles.get("en_jp")
        or data.get("titleO")
        or "Unknown"
    )


def _get_anime(anime_id: str) -> dict:
    response = scraper.get(API_URL + f"anime-by-id/{anime_id}")
    response.raise_for_status()
    return response.json()


def _load_catalogue() -> list:
    """Fetch (and cache) the full FRAnime catalogue."""
    global _catalogue, _catalogue_loaded_at

    if _catalogue is None or time.monotonic() - _catalogue_loaded_at > _CATALOGUE_TTL:
        response = scraper.get(API_URL + "animes")
        response.raise_for_status()
        # Some entries may lack seasons entirely
        _catalogue = [anime for anime in response.json() if isinstance(anime, dict)]
        _catalogue_loaded_at = time.monotonic()

    return _catalogue


def get_website_url():
    """Confirm the FRAnime API is reachable (warm up the catalogue cache)."""
    # FRAnime serves a fixed domain, unlike portals protected by anti-DDoS
    # fronts, so there is nothing to resolve. Warming up the catalogue here
    # keeps the first search instant instead of paying the API cost later.
    _load_catalogue()


def search(query: str) -> list[SearchResult]:
    """Filter the whole catalogue client-side, like the FRAnime website.

    The match is case- and accent-insensitive and covers every title
    variant (main title, original title, en_us, en_jp, ja_jp).
    """
    results: list[SearchResult] = []

    query = _normalize(query)

    for anime in _load_catalogue():

        # Gather the main and the alternative titles
        variants = {anime.get("title"), anime.get("titleO")}
        variants.update((anime.get("titles") or {}).values())
        titles = [_normalize(variant) for variant in variants if variant]

        # Keep animes whose titles match the query
        if any(query in title for title in titles):
            results.append(
                SearchResult(
                    title=_display_title(anime),
                    url=str(anime["id"]),
                    img=anime.get("affiche_small") or anime.get("affiche", ""),
                    genres=anime.get("themes") or [],
                    id=anime["id"],
                )
            )

    # Make animes whose main title contains the query appear first
    results.sort(key=lambda r: query not in _normalize(r.title))

    return results


def _normalize(text: str | None) -> str:
    """Lowercase and strip accents so queries match titles like 'Pokémon'."""
    if not text:
        return ""
    text = text.casefold().strip()
    # FRAnime titles use French/Japanese spellings, fold the accents away
    aliases: dict[str, str] = {
        "ë": "e", "é": "e", "è": "e", "ê": "e",
        "à": "a", "â": "a", "ä": "a",
        "î": "i", "ï": "i",
        "ô": "o", "ö": "o",
        "û": "u", "ü": "u", "ù": "u",
        "ç": "c",
    }
    return "".join(aliases.get(char, char) for char in text)


def get_series(selection) -> SamaSeries:
    """Load the anime structure: seasons with queryable URLs.

    ``selection`` can be a SearchResult or directly its ``id``.
    """
    anime_id = str(selection if isinstance(selection, (str, int)) else selection.id)

    data = _get_anime(anime_id)

    title = _display_title(data)
    img = data.get("affiche") or data.get("affiche_small", "")
    themes: list[str] = data.get("themes") or []
    saisons: list[dict] = data.get("saisons") or []

    seasons = [
        SeasonAccess(
            season.get("title") or f"Season {index + 1}",
            season_url(anime_id, index),
        )
        for index, season in enumerate(saisons)
    ]

    return SamaSeries(title, anime_id, img, themes, seasons)


def season_url(anime_id, season_index: int) -> str:
    """Encode the anime id and season index into a stable archive URL."""
    return f"{website_origin}/anime/{anime_id}/{season_index}"


def get_season(url: str) -> SamaSeason:
    """Build the season: episodes split per language, indexes kept.

    The FRAnime API lists every language on each episode. The player
    resolution happens later (see :func:`resolve_players`), so only an
    empty players list is stored here.
    """
    match = season_url_re.search(url)
    if not match:
        raise ValueError(f"Malformed FRAnime season URL: {url}")
    anime_id, season_index = match.groups()
    season_index = int(season_index)

    data = _get_anime(anime_id)
    saisons: list[dict] = data.get("saisons") or []
    if season_index >= len(saisons):
        raise NoEpisodesFoundError()

    season_data = saisons[season_index]

    episodes: dict[str, list[FranimeEpisode]] = {}

    for episode_index, episode_data in enumerate(season_data.get("episodes") or []):
        langs = episode_data.get("lang") or {}

        for lang in ("vo", "vf"):
            lecteurs = (langs.get(lang) or {}).get("lecteurs") or []
            if not lecteurs:
                continue

            episodes.setdefault(lang.upper(), []).append(
                FranimeEpisode(
                    title=episode_data.get("title") or f"Épisode {episode_index + 1}",
                    players=[],
                    index=episode_index,
                    lecteurs={lang: lecteurs},
                )
            )

    if not episodes:
        # The catalogue entry exists but nothing is playable: the content
        # is probably not released yet. Raise a clean error instead of
        # failing later in the flow.
        raise NoEpisodesFoundError()

    season_title = season_data.get("title") or "Saison inconnue"

    return SamaSeason(
        season_title,
        url,
        list(episodes.keys()),
        episodes,
    )


def resolve_players(
    anime_id, season_index: int, episode: FranimeEpisode, lang: str
) -> list[Player]:
    """Resolve every embed URL of one episode in the given ``"VO"``/``"VF"``.

    Each provider costs one resolver call plus a decryption, so this runs
    only for the selected episode.
    """
    lang = lang.lower()
    players: list[Player] = {}

    for lecteur_index, lecteur in enumerate(episode.lecteurs.get(lang, [])):
        try:
            watch2_url = _resolve_watch2(
                anime_id, season_index, episode.index, lang, lecteur_index
            )
            embed_url = _decrypt_watch2(watch2_url)
        except CloudflareChallengeError as e:
            # Every lecteur will fail the same way: no point retrying them.
            print_error(str(e))
            return []
        except Exception as e:
            print_warning(f" - {lecteur}: failed to resolve ({e})")
            continue

        if embed_url:
            # The same URL resolved twice is the same embed, not a new
            # source; FRAnime does list duplicate lecteur names.
            if embed_url not in players:
                players[embed_url] = Player(name=lecteur, url=embed_url)
        else:
            print_warning(f" - {lecteur}: failed to decrypt")

    return list(players.values())


class CloudflareChallengeError(Exception):
    pass


def _resolve_watch2(anime_id, season_index, episode_index, lang, lecteur_index) -> str:
    """Fetch the plain-text watch2 URL returned by the lecteur resolver."""
    response = scraper.get(
        API_URL
        + f"anime/{anime_id}/{season_index}/{episode_index}/{lang}/{lecteur_index}"
    )
    response.raise_for_status()

    text = response.text.strip()

    if "watch2" in text:
        return text

    # When the API is rate-limited it also answers with HTML challenge
    # pages and placeholder links (always the same domain, whatever the
    # lecteur, changing on every call). Report both cleanly.
    lowered = text.lower()
    if lowered.startswith("<!doctype") or "just a moment" in lowered:
        raise CloudflareChallengeError(
            "The FRAnime API is asking for a Cloudflare check: wait a "
            "little and try again."
        )
    raise ValueError(
        "FRAnime served a non-playable link (this can happen when the API "
        "is rate-limited, wait a bit and retry)."
    )


def _decrypt_watch2(watch2_url: str) -> str | None:
    """Brute-force the single-byte XOR key of a watch2 URL offline.

    Every query parameter holds base64-encoded hexadecimal bytes that XOR
    a provider URL with a key changing regularly between 0 and 255. We try
    all of them and keep the parameter decrypting to a URL pointing at a
    known provider domain.
    """
    best: str | None = None

    params = urllib.parse.parse_qs(urllib.parse.urlparse(watch2_url).query)
    for values in params.values():
        try:
            decoded = base64.b64decode(values[0]).decode("utf-8")
        except (binascii.Error, UnicodeDecodeError, ValueError):
            continue

        # The payload must be a plain hexadecimal string
        if len(decoded) % 2 != 0 or not all(c in string.hexdigits for c in decoded):
            continue

        encrypted = bytes.fromhex(decoded)
        for key in range(256):
            try:
                candidate = bytes(byte ^ key for byte in encrypted).decode("utf-8")
            except UnicodeDecodeError:
                continue

            if not candidate.startswith(("http://", "https://")):
                continue

            if any(provider in candidate for provider in KNOWN_PROVIDERS):
                # A confirmed provider match beats any guess
                return candidate
            # Keep the first printable URL as a fallback guess
            if best is None and all(c in string.printable for c in candidate):
                best = candidate

    return best
