"""Data types shared by the subtitle providers and the extractor."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class SubtitleQuery:
    """What the caller is looking for."""

    imdb_id: str | None = None
    season: int | None = None
    episode: int | None = None
    # Canonical ISO 639-1 code (see :mod:`language_tags`), or ``None``.
    language: str | None = None
    anidb_id: int | None = None
    # Release label of the stream being played, used to prefer a subtitle
    # uploaded for the same release (same group / resolution).
    release: str | None = None

    @property
    def is_episode(self) -> bool:
        # Season/episode 0 are valid (specials, prologues): test for presence,
        # not truthiness.
        return self.season is not None and self.episode is not None


@dataclass(frozen=True)
class Subtitle:
    """A single downloadable subtitle track.

    ``priority`` is internal: lower values are more trustworthy and are listed
    first. It is intentionally not exposed by :meth:`to_dict`.
    """

    url: str
    source: str
    language: str = ""
    label: str = ""
    title: str = ""
    fmt: str = "srt"
    priority: int = 100
    headers: dict[str, str] = field(default_factory=dict)
    # Provider-side identity, used to de-duplicate the same upload surfaced by
    # several add-ons (OpenSubtitles ``sub_id``).
    sub_id: str = ""
    trusted: bool = False
    ai_translated: bool = False
    hearing_impaired: bool = False
    fps: float | None = None
    incomplete: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Mapping form consumed by the players and the CLI handlers."""
        data: dict[str, Any] = {
            "url": self.url,
            "source": self.source,
            "lang": self.language,
            "label": self.label,
            "title": self.title,
            "format": self.fmt,
        }
        if self.headers:
            data["headers"] = dict(self.headers)
        if self.sub_id:
            data["sub_id"] = self.sub_id
        if self.trusted:
            data["trusted"] = True
        if self.ai_translated:
            data["ai_translated"] = True
        if self.hearing_impaired:
            data["hi"] = True
        if self.fps:
            data["fps"] = self.fps
        if self.incomplete:
            data["incomplete"] = True
        return data
