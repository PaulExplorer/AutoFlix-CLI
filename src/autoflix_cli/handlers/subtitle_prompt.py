"""Shared "add extra subtitles?" prompt for every playback flow.

Any provider that plays through
:func:`autoflix_cli.handlers.playback.play_episode_flow` gets the same
question right before the video starts: do you want to add external
subtitles? On yes, the track is searched through the keyless providers of
:mod:`autoflix_cli.scraping.subtitles` and handed to
:func:`autoflix_cli.player_manager.play_video`.
"""

from __future__ import annotations

import re
import urllib.parse

from curl_cffi import requests

from ..cli_utils import (
    get_user_input,
    print_info,
    print_success,
    print_warning,
    select_from_list,
)
from ..languages import get_language_label
from ..scraping.subtitles import subtitle_extractor
from ..tracker import tracker

CINEMETA_SERIES = "https://v3-cinemeta.strem.io/catalog/series/top/search={query}.json"
CINEMETA_MOVIE = "https://v3-cinemeta.strem.io/catalog/movie/top/search={query}.json"

_ANY_NUMBER = re.compile(r"\d+")
# "Saison 2", "Season 2" or "S2"; a bare number is intentionally NOT a season
# so a series title reused as a season label cannot leak a wrong number.
_SEASON_MARKER = re.compile(r"(?:saison|season)\s*(\d+)|\bs(\d{1,2})\b", re.IGNORECASE)

_MAX_RESULTS = 8


def parse_number(value) -> int | None:
    """First integer found in ``value`` (``"Episode 12"`` -> ``12``)."""
    if value is None:
        return None
    if isinstance(value, int):
        return value
    match = _ANY_NUMBER.search(str(value))
    return int(match.group()) if match else None


def parse_season(value) -> int | None:
    """Season number from a label (``"Saison 2 (VF)"`` or ``"S2"`` -> ``2``).

    Returns ``None`` when the label carries no season marker.
    """
    if value is None:
        return None
    match = _SEASON_MARKER.search(str(value))
    if not match:
        return None
    return int(match.group(1) or match.group(2))


def _cinemeta_matches(title: str) -> list[dict]:
    """Cinemeta (Stremio, keyless) catalogue entries matching ``title``."""
    metas: list[dict] = []
    for endpoint in (CINEMETA_SERIES, CINEMETA_MOVIE):
        url = endpoint.format(query=urllib.parse.quote(title))
        try:
            payload = requests.get(
                url, timeout=8, impersonate="chrome", allow_redirects="safe"
            ).json()
        except Exception:
            continue
        metas.extend(payload.get("metas") or [])
    return [meta for meta in metas if meta.get("imdb_id")][:7]


def _ask_manual_imdb_id() -> str | None:
    value = get_user_input("IMDB ID (e.g. tt0388629, blank to skip)")
    return value or None


def resolve_imdb_id(title: str) -> tuple[str | None, bool]:
    """Let the user pick the IMDB entry matching ``title``.

    Returns ``(imdb_id, is_movie)``; ``(None, False)`` when skipped.
    """
    matches = _cinemeta_matches(title)
    if not matches:
        return _ask_manual_imdb_id(), False

    options = [
        f"{meta.get('name')} ({meta.get('year', '?')}) - {meta.get('type', 'series')}"
        for meta in matches
    ]
    options += ["Enter manually", "Skip subtitles", "← Back"]
    index = select_from_list(options, f"Select IMDB match for '{title}':")

    if index < len(matches):
        meta = matches[index]
        return meta["imdb_id"], meta.get("type") == "movie"
    if index == len(matches):
        return _ask_manual_imdb_id(), False
    return None, False


def _anilist_ids(anilist_id: int) -> tuple[str | None, int | None]:
    """Resolve ``(imdb_id, anidb_id)`` for an AniList id via the mapping API."""
    try:
        from ..scraping.goldenanime import goldenanime

        mappings = goldenanime.get_mappings(anilist_id) or {}
    except Exception:
        return None, None

    imdb_id = mappings.get("imdbId")
    if imdb_id and not str(imdb_id).startswith("tt"):
        imdb_id = f"tt{imdb_id}"
    return (imdb_id or None), (mappings.get("anidbId") or None)


def _describe_subtitle(subtitle: dict) -> str:
    label = subtitle.get("label") or subtitle.get("lang") or "?"
    title = (subtitle.get("title") or "").strip()
    base = f"{subtitle.get('source', '?')} · {label}"
    return f"{base} · {title[:45]}" if title else base


def prompt_extra_subtitles(
    *,
    title: str | None = None,
    imdb_id: str | None = None,
    anidb_id: int | None = None,
    anilist_id: int | None = None,
    season: int | None = None,
    episode: int | None = None,
    language: str | None = None,
) -> list[dict]:
    """Ask whether to add external subtitles and return the chosen track(s).

    The result is a list (empty when declined or nothing is found) ready to be
    passed to ``play_video(subtitles=...)``.
    """
    user_lang = language or tracker.get_language() or "fr"
    lang_name = get_language_label(user_lang)

    if select_from_list(["Yes", "No"], f"Add {lang_name} subtitles?") != 0:
        return []

    if anilist_id:
        mapped_imdb, mapped_anidb = _anilist_ids(anilist_id)
        imdb_id = imdb_id or mapped_imdb
        anidb_id = anidb_id or mapped_anidb

    if not imdb_id and not anidb_id and title:
        imdb_id, is_movie = resolve_imdb_id(title)
        if is_movie:
            season, episode = None, None

    if not imdb_id and not anidb_id:
        return []

    print_info(f"Searching for {lang_name} subtitles...")
    results = subtitle_extractor.search(
        imdb_id=imdb_id,
        season=season,
        episode=episode,
        lang_filter=user_lang,
        anidb_id=anidb_id,
    )
    if not results:
        print_warning(f"No {lang_name} subtitles found.")
        return []

    shown = results[:_MAX_RESULTS]
    options = [_describe_subtitle(sub) for sub in shown] + ["← Cancel"]
    index = select_from_list(options, "📝 Select subtitle track:")
    if index >= len(shown):
        return []

    chosen = shown[index]
    print_success(f"Subtitle selected from {chosen['source']}.")
    return [chosen]
