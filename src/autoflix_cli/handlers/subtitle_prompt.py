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

from ..cli_utils import (
    get_user_input,
    print_info,
    print_success,
    print_warning,
    select_from_list,
)
from ..languages import get_language_label
from ..scraping import metadata
from ..scraping.subtitles import subtitle_extractor
from ..tracker import tracker

_ANY_NUMBER = re.compile(r"\d+")
# Explicit episode markers, tried before any loose number so a title that
# contains digits ("The 100 — S01E02") cannot be mistaken for the episode.
_EXPLICIT_EPISODE = re.compile(
    r"\bS(\d{1,2})\s*E(\d{1,3})\b|(?<!\d)(\d{1,2})x(\d{1,3})(?!\d)",
    re.IGNORECASE,
)
_EPISODE_WORD = re.compile(
    r"\b(?:episode|épisode|ep|e)\s*\.?\s*(\d{1,3})\b", re.IGNORECASE
)
# "Saison 2", "Season 2" or "S2"; a bare number is intentionally NOT a season
# so a series title reused as a season label cannot leak a wrong number.
_SEASON_MARKER = re.compile(r"(?:saison|season)\s*(\d+)|\bs(\d{1,2})\b", re.IGNORECASE)

_MAX_RESULTS = 8


def parse_number(value) -> int | None:
    """Episode number found in ``value``.

    Explicit markers (``"S01E02"``, ``"1x02"``, ``"Episode 2"``) win over the
    first loose number, so a title embedding digits (``"The 100 — S01E02"``)
    still resolves to ``2``.
    """
    if value is None:
        return None
    if isinstance(value, int):
        return value
    text = str(value)

    explicit = _EXPLICIT_EPISODE.search(text)
    if explicit:
        return int(explicit.group(2) or explicit.group(4))

    word = _EPISODE_WORD.search(text)
    if word:
        return int(word.group(1))

    match = _ANY_NUMBER.search(text)
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


def _cinemeta_matches(
    title: str, is_movie: bool | None = None, year: int | None = None
) -> list[dict]:
    """Cinemeta (Stremio, keyless) entries matching ``title``, best first.

    Unlike a raw catalogue query, every result is scored against the title,
    year and media type: a movie named "Memories" must beat the dozen series
    sharing the word. The list is only truncated *after* ranking.
    """
    return metadata.cinemeta_candidates(title, is_movie, year)


def _ask_manual_imdb_id() -> str | None:
    value = get_user_input("IMDB ID (e.g. tt0388629, blank to skip)")
    return value or None


def _candidate_label(candidate: dict) -> str:
    kind = "movie" if candidate.get("is_movie") else "series"
    year = candidate.get("year") or "?"
    return f"{candidate.get('title') or '?'} ({year}) - {kind}"


def resolve_imdb_id(
    title: str,
    is_movie: bool | None = None,
    year: int | None = None,
) -> tuple[str | None, bool]:
    """Let the user pick the IMDB entry matching ``title``.

    TMDB is tried first (it ranks localized titles and knows the exact media
    type), then Cinemeta as a keyless fallback. Returns ``(imdb_id,
    is_movie)``; ``(None, False)`` when skipped.
    """
    matches: list[dict] = []
    try:
        matches = metadata.search_titles(title, is_movie, year)
    except Exception:  # noqa: BLE001 - fall back to Cinemeta
        matches = []
    if not matches:
        matches = _cinemeta_matches(title, is_movie, year)
    matches = matches[:8]

    if not matches:
        return _ask_manual_imdb_id(), False

    options = [_candidate_label(meta) for meta in matches]
    options += ["Enter manually", "Skip subtitles", "← Back"]
    index = select_from_list(options, f"Select IMDB match for '{title}':")

    if index < len(matches):
        meta = matches[index]
        return meta["imdb_id"], bool(meta.get("is_movie"))
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


def describe_subtitle(subtitle: dict) -> str:
    label = subtitle.get("label") or subtitle.get("lang") or "?"
    title = (subtitle.get("title") or "").strip()
    tags = []
    if subtitle.get("trusted"):
        tags.append("trusted")
    if subtitle.get("ai_translated"):
        tags.append("AI")
    if subtitle.get("incomplete"):
        tags.append("CD1")
    if subtitle.get("hi"):
        tags.append("HI")
    suffix = "".join(f" [{tag}]" for tag in tags)
    base = f"{subtitle.get('source', '?')} · {label}{suffix}"
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
    is_movie: bool | None = None,
    year: int | None = None,
    release: str | None = None,
) -> list[dict]:
    """Ask whether to add external subtitles and return the chosen track(s).

    The result is a list (empty when declined or nothing is found) ready to be
    passed to ``play_video(subtitles=...)``.
    """
    user_lang = language or tracker.get_language() or "fr"
    lang_name = get_language_label(user_lang)

    # "No" comes first (and is preselected) so a stray Enter skips the
    # optional subtitle search; subtitles are opt-in.
    if select_from_list(["No", "Yes"], f"Add {lang_name} subtitles?") == 0:
        return []

    if anilist_id:
        mapped_imdb, mapped_anidb = _anilist_ids(anilist_id)
        imdb_id = imdb_id or mapped_imdb
        anidb_id = anidb_id or mapped_anidb

    if not imdb_id and not anidb_id and title:
        imdb_id, is_movie = resolve_imdb_id(title, is_movie, year)
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
        release=release,
    )
    if not results:
        print_warning(f"No {lang_name} subtitles found.")
        return []

    shown = results[:_MAX_RESULTS]
    options = [describe_subtitle(sub) for sub in shown] + ["← Cancel"]
    index = select_from_list(options, "📝 Select subtitle track:")
    if index >= len(shown):
        return []

    chosen = shown[index]
    print_success(f"Subtitle selected from {chosen['source']}.")
    return [chosen]
