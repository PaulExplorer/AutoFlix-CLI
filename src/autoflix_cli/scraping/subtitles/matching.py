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

# Extensions that end a URL path, optionally followed by a slash (the
# stremio.homes add-on serves ``/sub.vtt/?sub_id=...``), query or fragment.
_SUFFIX_RE = re.compile(r"\.([a-z0-9]{2,4})(?:[/?#].*)?$", re.IGNORECASE)

# Multi-part subtitle uploads: only the first CD is useless on its own.
_INCOMPLETE_RE = re.compile(
    r"(?:^|[^a-z0-9])(?:cd\s*1|1\s*cd|part\s*1|disc\s*1|dvd\s*1)(?:[^a-z0-9]|$)",
    re.IGNORECASE,
)
_QUALITY_RE = re.compile(r"\b(2160p|1080p|720p|480p|bluray|blu-ray|webrip|web-dl|hdtv|dvdrip)\b", re.IGNORECASE)


def matches_episode(name: str, episode: int | None, season: int | None = None) -> bool:
    """Heuristically match a release or file name against an episode number."""
    if episode is None:
        return False

    lowered = name.lower()
    pinned = str(episode).zfill(2)
    plain = str(episode)

    if season is not None:
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


def is_incomplete(name: str) -> bool:
    """Whether an upload only carries the first CD/part of the movie."""
    return bool(_INCOMPLETE_RE.search(name or ""))


def release_similarity(release: str | None, name: str | None) -> float:
    """How well a subtitle filename matches the release being played.

    A same-release subtitle is already in sync, so it should win over a
    generic upload even when both come from the same provider. Only cheap,
    reliable signals are used: quality tag and release group tokens.
    """
    if not release or not name:
        return 0.0
    wanted = release.lower()
    candidate = name.lower()
    score = 0.0
    wanted_quality = {match.group(1).lower() for match in _QUALITY_RE.finditer(wanted)}
    candidate_quality = {match.group(1).lower() for match in _QUALITY_RE.finditer(candidate)}
    if wanted_quality and wanted_quality & candidate_quality:
        score += 0.5
    # Release groups are the token after the last dot/dash in scene names.
    wanted_group = re.split(r"[.\-]", wanted.rstrip("]"))[-1]
    if len(wanted_group) > 2 and wanted_group in candidate:
        score += 0.5
    return score


def guess_format(url: str) -> str:
    """Infer a subtitle format from a URL, defaulting to ``srt``."""
    match = _SUFFIX_RE.search(url)
    if match:
        return _FORMAT_BY_SUFFIX.get(match.group(1).lower(), match.group(1).lower())
    return "srt"
