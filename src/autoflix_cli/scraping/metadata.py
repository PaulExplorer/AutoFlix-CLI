"""Keyless title -> IMDB resolution.

Subtitle providers are keyed by IMDB id, but most scraped pages only expose a
human title (sometimes with a year or a season marker). Cinemeta alone is a
poor resolver: its search endpoint mixes movies and series and returns the
catalogue order, so a film can be buried under a dozen same-named series.

This module queries the public TMDB proxy already used by the CloudStream
extensions (no API key), scores every result against the requested title,
year and media type, then reads ``external_ids`` to get the IMDB id.
Cinemeta stays as a fallback and as the final candidate list.
"""

from __future__ import annotations

import difflib
import re
import unicodedata
import urllib.parse

from curl_cffi import requests

from ..log import log
from .config import portals

DEFAULT_TMDB_BASE = "https://theemoviedb.hexa.su/api/tmdb"
TMDB_TIMEOUT = 10
MAX_CANDIDATES = 8
MAX_EXTERNAL_LOOKUPS = 6

_YEAR_IN_TITLE = re.compile(r"\((?:19|20)\d{2}\)")
_ANY_YEAR = re.compile(r"\b(19|20)\d{2}\b")

_cache: dict[tuple, list[dict]] = {}


def tmdb_base() -> str:
    """Base URL of the keyless TMDB proxy (overridable via portals)."""
    return (portals.get("tmdb") or DEFAULT_TMDB_BASE).rstrip("/")


def normalize_title(value: str) -> str:
    """Lowercase, accent-free, punctuation-free form used for comparison."""
    text = unicodedata.normalize("NFKD", value or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower()
    text = re.sub(r"\(\s*(?:19|20)\d{2}\s*\)", " ", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def year_from_title(title: str) -> int | None:
    """Year embedded in a display title (``"Memories (1995)"`` -> 1995)."""
    if not title:
        return None
    match = _ANY_YEAR.search(str(title))
    return int(match.group()) if match else None


def title_similarity(wanted: str, candidate: str) -> float:
    """0..1 similarity robust to punctuation, accents and localized titles."""
    left = normalize_title(wanted)
    right = normalize_title(candidate)
    if not left or not right:
        return 0.0
    if left == right:
        return 1.0
    if right.startswith(left) or left.startswith(right):
        return 0.9
    if left in right or right in left:
        return 0.8
    return difflib.SequenceMatcher(None, left, right).ratio()


def score_candidate(
    title: str,
    year: int | None,
    is_movie: bool | None,
    candidate: dict,
) -> float:
    """Rank a TMDB/Cinemeta result against the requested title.

    Title similarity dominates; year and media type only break ties, so a
    localized title still wins over an exact but unrelated same-name entry.
    """
    score = title_similarity(title, candidate.get("title") or "")
    candidate_year = candidate.get("year")
    if year and candidate_year:
        if year == candidate_year:
            score += 0.35
        elif abs(year - candidate_year) <= 1:
            score += 0.15
        else:
            score -= 0.35
    if is_movie is not None and candidate.get("is_movie") is not None:
        score += 0.1 if is_movie == candidate.get("is_movie") else -0.5
    return score


def _tmdb_get(path: str, params: dict | None = None):
    url = f"{tmdb_base()}/{path.lstrip('/')}"
    response = requests.get(
        url,
        params=params or {},
        timeout=TMDB_TIMEOUT,
        impersonate="chrome",
        allow_redirects="safe",
    )
    response.raise_for_status()
    return response.json()


def _tmdb_search(title: str, is_movie: bool | None, year: int | None) -> list[dict]:
    if is_movie is True:
        endpoint, media_type = "search/movie", "movie"
    elif is_movie is False:
        endpoint, media_type = "search/tv", "tv"
    else:
        endpoint, media_type = "search/multi", None

    params: dict = {"query": title, "language": "fr-FR", "include_adult": "false"}
    if year and media_type == "movie":
        params["year"] = year
    elif year and media_type == "tv":
        params["first_air_date_year"] = year

    payload = _tmdb_get(endpoint, params)
    results = payload.get("results") if isinstance(payload, dict) else None
    if not isinstance(results, list):
        return []

    candidates: list[dict] = []
    for result in results:
        kind = result.get("media_type") or media_type
        if kind not in ("movie", "tv"):
            continue
        date = result.get("release_date") or result.get("first_air_date") or ""
        candidates.append(
            {
                "tmdb_id": result.get("id"),
                "title": result.get("title") or result.get("name") or "",
                "year": int(date[:4]) if date[:4].isdigit() else None,
                "is_movie": kind == "movie",
                "type": kind,
            }
        )
    return candidates


def _with_imdb_ids(candidates: list[dict]) -> list[dict]:
    """Attach ``imdb_id`` to the most promising candidates."""
    resolved: list[dict] = []
    for candidate in candidates[:MAX_EXTERNAL_LOOKUPS]:
        tmdb_id = candidate.get("tmdb_id")
        kind = "movie" if candidate.get("is_movie") else "tv"
        if not tmdb_id:
            continue
        try:
            external = _tmdb_get(f"{kind}/{tmdb_id}/external_ids")
        except Exception as exc:  # noqa: BLE001 - one miss must not abort
            log.debug("TMDB external_ids failed for %s: %s", tmdb_id, exc)
            continue
        imdb_id = (external or {}).get("imdb_id")
        if not imdb_id:
            continue
        resolved.append({**candidate, "imdb_id": imdb_id})
    return resolved


def search_titles(
    title: str,
    is_movie: bool | None = None,
    year: int | None = None,
    *,
    limit: int = MAX_CANDIDATES,
) -> list[dict]:
    """Scored TMDB candidates carrying an IMDB id, best match first."""
    title = (title or "").strip()
    if not title:
        return []
    year = year or year_from_title(title)
    clean_title = _YEAR_IN_TITLE.sub(" ", title).strip()
    key = (normalize_title(clean_title), is_movie, year)
    if key in _cache:
        return _cache[key][:limit]

    try:
        candidates = _tmdb_search(clean_title, is_movie, year)
    except Exception as exc:  # noqa: BLE001 - fallback handled by the caller
        log.warning("TMDB search failed for %r: %s", title, exc)
        return []

    candidates.sort(
        key=lambda candidate: score_candidate(clean_title, year, is_movie, candidate),
        reverse=True,
    )
    resolved = _with_imdb_ids(candidates)
    _cache[key] = resolved
    return resolved[:limit]


def resolve_imdb(
    title: str,
    is_movie: bool | None = None,
    year: int | None = None,
) -> tuple[str | None, bool | None]:
    """Best ``(imdb_id, is_movie)`` guess for a title, or ``(None, None)``."""
    candidates = search_titles(title, is_movie, year, limit=1)
    if not candidates:
        return None, None
    best = candidates[0]
    return best.get("imdb_id"), best.get("is_movie")


def tmdb_number_of_seasons(tmdb_id: int) -> int | None:
    """Season count for a series, used to build an honest season menu."""
    if not tmdb_id:
        return None
    try:
        payload = _tmdb_get(f"tv/{tmdb_id}", {"language": "fr-FR"})
    except Exception:  # noqa: BLE001
        return None
    count = payload.get("number_of_seasons") if isinstance(payload, dict) else None
    return count if isinstance(count, int) and count > 0 else None


def cinemeta_candidates(
    title: str,
    is_movie: bool | None = None,
    year: int | None = None,
) -> list[dict]:
    """Cinemeta fallback, ranked like the TMDB candidates."""
    endpoints = []
    if is_movie is not False:
        endpoints.append(("movie", "https://v3-cinemeta.strem.io/catalog/movie/top/search={query}.json"))
    if is_movie is not True:
        endpoints.append(("series", "https://v3-cinemeta.strem.io/catalog/series/top/search={query}.json"))

    metas: list[dict] = []
    for kind, endpoint in endpoints:
        url = endpoint.format(query=urllib.parse.quote(title))
        try:
            payload = requests.get(
                url, timeout=8, impersonate="chrome", allow_redirects="safe"
            ).json()
        except Exception:
            continue
        for meta in payload.get("metas") or []:
            if not meta.get("imdb_id"):
                continue
            release = str(meta.get("releaseInfo") or meta.get("year") or "")
            metas.append(
                {
                    "imdb_id": meta["imdb_id"],
                    "title": meta.get("name") or "",
                    "year": int(release[:4]) if release[:4].isdigit() else None,
                    "is_movie": (meta.get("type") or kind) == "movie",
                    "type": meta.get("type") or kind,
                }
            )

    year = year or year_from_title(title)
    clean_title = _YEAR_IN_TITLE.sub(" ", title).strip()
    metas.sort(
        key=lambda candidate: score_candidate(clean_title, year, is_movie, candidate),
        reverse=True,
    )
    return metas
