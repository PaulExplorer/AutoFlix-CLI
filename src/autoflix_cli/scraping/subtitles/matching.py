"""Release/file name heuristics used to pick the right subtitle file."""

from __future__ import annotations

import re

_FORMAT_BY_SUFFIX = {
    "ass": "ass",
    "ssa": "ssa",
    "srt": "srt",
    "sub": "sub",
    "vtt": "vtt",
}

# Extensions that end a URL path (optionally followed by a query string).
_SUFFIX_RE = re.compile(r"\.([a-z0-9]{2,4})(?:[?#].*)?$", re.IGNORECASE)


def matches_episode(name: str, episode: int | None, season: int | None = None) -> bool:
    """Heuristically match a release or file name against an episode number."""
    if episode is None:
        return False

    lowered = name.lower()
    pinned = str(episode).zfill(2)
    plain = str(episode)

    if season:
        # Prefer explicit SxxEyy patterns (e.g. s01e05, 1x05).
        for season_token in (str(season).zfill(2), str(season)):
            for episode_token in (pinned, plain):
                if re.search(rf"\b(?:s|season\s*){season_token}[ex]{episode_token}\b", lowered):
                    return True
                if re.search(rf"{season_token}x{episode_token}\b", lowered):
                    return True

    # Bare episode token, e.g. " - 01 -", "[01]". The lookarounds exclude the
    # digits inside "S01", "S01E12", "ep05", "1080p", ...
    if re.search(rf"(?<![a-z0-9]){pinned}(?![a-z0-9])", lowered):
        return True
    if re.search(rf"(?<![a-z0-9]){plain}(?![a-z0-9])", lowered):
        return True
    if re.search(rf"\bep(?:isode\s*)?{pinned}\b", lowered):
        return True
    return False


def is_batch(name: str) -> bool:
    """Whether a release name looks like a season/complete pack."""
    lowered = name.lower()
    return bool(re.search(r"\bs\d{1,2}\b", lowered)) or any(
        tag in lowered for tag in ("batch", "complete", "collection")
    )


def guess_format(url: str) -> str:
    """Infer a subtitle format from a URL, defaulting to ``srt``."""
    match = _SUFFIX_RE.search(url)
    if match:
        return _FORMAT_BY_SUFFIX.get(match.group(1).lower(), match.group(1).lower())
    return "srt"
