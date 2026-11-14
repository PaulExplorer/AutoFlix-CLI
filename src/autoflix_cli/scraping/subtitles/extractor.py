"""Subtitle orchestration: fetch from every provider, filter, rank, de-dupe."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from ...log import log
from ..config import portals
from .language_tags import normalize_language
from .matching import release_similarity
from .models import Subtitle, SubtitleQuery
from .providers import (
    DEFAULT_LANGUAGES,
    AnimeToshoProvider,
    StremioSubtitleProvider,
    SubtitleProvider,
)

# Base URLs, overridable through data/source_portal.jsonc.
HOMES_URL = "https://opensubtitles.stremio.homes"
STREMIO_URL = "https://opensubtitles-v3.strem.io"
ANIMETOSHO_URL = "https://feed.animetosho.xyz"


def default_providers() -> list[SubtitleProvider]:
    """The built-in keyless providers, ranked from most to least trusted."""
    return [
        StremioSubtitleProvider(
            "OpenSubtitles (Homes)",
            portals.get("opensubtitles-homes", HOMES_URL),
            priority=1,
            language_scoped=True,
            default_languages=DEFAULT_LANGUAGES,
        ),
        StremioSubtitleProvider(
            "OpenSubtitles (Stremio)",
            portals.get("opensubtitles-stremio", STREMIO_URL),
            priority=2,
        ),
        AnimeToshoProvider(
            portals.get("animetosho", ANIMETOSHO_URL),
            max_releases=3,
        ),
    ]


def deduplicate(subtitles: list[Subtitle]) -> list[Subtitle]:
    """Drop the same upload surfaced twice.

    OpenSubtitles is reachable through several add-ons: the same ``sub_id``
    can appear in more than one answer. De-duplicating on the id (then URL,
    then language/title) keeps one copy per real upload.
    """
    seen_ids: set[str] = set()
    seen_urls: set[str] = set()
    seen_lang_titles: set[tuple[str, str]] = set()
    unique: list[Subtitle] = []
    for subtitle in subtitles:
        if subtitle.sub_id:
            key = f"id:{subtitle.sub_id}"
            if key in seen_ids:
                continue
            seen_ids.add(key)
        if subtitle.url in seen_urls:
            continue
        seen_urls.add(subtitle.url)
        lang_title = (subtitle.language, subtitle.title)
        if subtitle.title and lang_title in seen_lang_titles:
            continue
        seen_lang_titles.add(lang_title)
        unique.append(subtitle)
    return unique


def _rank_key(subtitle: Subtitle, release: str | None = None) -> tuple:
    """Deterministic confidence order (lower is better).

    Source trust first, then human over AI, complete over CD1-only, and a
    same-release filename ahead of an unrelated upload.
    """
    return (
        subtitle.priority,
        0 if subtitle.trusted else 1,
        1 if subtitle.incomplete else 0,
        1 if subtitle.ai_translated else 0,
        -release_similarity(release, subtitle.title),
        subtitle.title.lower(),
        subtitle.url,
    )


class SubtitleExtractor:
    """Library-friendly subtitle search.

    Results are returned as plain dictionaries (``url``/``source``/``lang``/
    ``label``/``title``/``format``) sorted by order of confidence, so callers
    such as the golden-* handlers need no changes.
    """

    def __init__(self, providers: list[SubtitleProvider] | None = None):
        self.providers = list(providers) if providers is not None else default_providers()

    def search(
        self,
        imdb_id: str | None,
        season: int | None = None,
        episode: int | None = None,
        lang_filter: str | None = None,
        anidb_id: int | None = None,
        release: str | None = None,
    ) -> list[dict]:
        """Search, filter and sort subtitles by order of confidence.

        :param lang_filter: Language code or name (e.g. ``"fr"``, ``"French"``).
        :param anidb_id: AniDB id used by AnimeTosho (optional).
        :param release: Release label of the stream being played (optional).
        """
        wanted = normalize_language(lang_filter)
        query = SubtitleQuery(
            imdb_id=imdb_id,
            season=season,
            episode=episode,
            language=wanted,
            anidb_id=anidb_id,
            release=release,
        )

        collected: list[Subtitle] = []
        if not self.providers:
            return []
        # Every provider is an independent HTTP call: run them concurrently so
        # a slow/dead add-on cannot delay the whole menu.
        with ThreadPoolExecutor(max_workers=len(self.providers)) as pool:
            futures = [pool.submit(provider.fetch, query) for provider in self.providers]
            for provider, future in zip(self.providers, futures, strict=False):
                try:
                    collected.extend(future.result())
                except Exception as exc:  # noqa: BLE001 - a broken source is skipped
                    log.warning("Subtitle provider %s failed: %s", provider.name, exc)

        collected = [sub for sub in collected if sub.url]
        if wanted:
            collected = [sub for sub in collected if sub.language == wanted]

        # Rank before de-duplicating so the most trusted duplicate survives.
        collected.sort(key=lambda sub: _rank_key(sub, release))
        return [sub.to_dict() for sub in deduplicate(collected)]


# Global instance kept for backward compatibility with existing imports.
subtitle_extractor = SubtitleExtractor()
