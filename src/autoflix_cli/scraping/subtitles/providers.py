"""Keyless subtitle providers.

Every provider here relies on a public endpoint that needs no API key, so the
CLI keeps working out of the box. Providers only *fetch and parse*; filtering,
ranking and de-duplication are the extractor's job.
"""

from __future__ import annotations

from curl_cffi import requests

from ...log import log
from .language_tags import language_label, normalize_language
from .matching import guess_format, is_batch, is_incomplete, matches_episode
from .models import Subtitle, SubtitleQuery

REQUEST_TIMEOUT = 15

# Language prefix used by the stremio.homes add-on when the caller gave no
# preference. The add-on caps the list at 10 languages, so French goes first
# and the rest is a broad set that keeps other languages in the result set.
DEFAULT_LANGUAGES = ("fr", "en", "hi", "de", "ar", "tr", "es", "ta", "te", "ru")

# Options accepted by the stremio.homes route. ``ai-translated=true`` widens
# the catalogue with machine-translated tracks (labelled [AI] by the
# extractor) instead of silently dropping them.
HOMES_OPTIONS = "ai-translated=true|from=all|auto-adjustment=true"

_session: requests.Session | None = None


def http_session() -> requests.Session:
    """Shared curl_cffi session impersonating Chrome (Cloudflare-friendly)."""
    global _session
    if _session is None:
        _session = requests.Session(impersonate="chrome")
    return _session


def fetch_json(url: str, session: requests.Session | None = None):
    """GET ``url`` and decode its JSON body."""
    session = session or http_session()
    response = session.get(url, timeout=REQUEST_TIMEOUT, allow_redirects="safe")
    response.raise_for_status()
    return response.json()


class SubtitleProvider:
    """Base class: a named, ranked source of subtitles."""

    name = "provider"
    priority = 100

    def __init__(self, session: requests.Session | None = None):
        self._session = session

    def fetch(self, query: SubtitleQuery) -> list[Subtitle]:
        raise NotImplementedError

    def _get_json(self, url: str):
        return fetch_json(url, self._session)


class StremioSubtitleProvider(SubtitleProvider):
    """OpenSubtitles exposed through a public Stremio subtitle add-on.

    Two flavours exist:

    * bare routes -- ``/subtitles/movie/<imdb>.json`` (legacy strem.io bridge);
    * language-scoped routes -- ``/<langs>/<options>/subtitles/...`` required
      by the stremio.homes add-on, whose route 404s without a config prefix.
    """

    def __init__(
        self,
        name: str,
        base_url: str,
        priority: int = 2,
        *,
        language_scoped: bool = False,
        default_languages: tuple[str, ...] = DEFAULT_LANGUAGES,
        session: requests.Session | None = None,
    ):
        super().__init__(session)
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.priority = priority
        self.language_scoped = language_scoped
        self.default_languages = default_languages

    def fetch(self, query: SubtitleQuery) -> list[Subtitle]:
        if not query.imdb_id:
            return []
        try:
            payload = self._get_json(self._endpoint(query))
        except Exception as exc:  # noqa: BLE001 - one dead source must not abort
            log.warning("Subtitle source %s failed: %s", self.name, exc)
            return []
        entries = payload.get("subtitles") if isinstance(payload, dict) else None
        if not isinstance(entries, list):
            return []
        return [sub for sub in (self._parse(e) for e in entries if isinstance(e, dict)) if sub.url]

    def _endpoint(self, query: SubtitleQuery) -> str:
        if query.is_episode:
            resource = f"series/{query.imdb_id}:{query.season}:{query.episode}"
        else:
            resource = f"movie/{query.imdb_id}"
        if self.language_scoped:
            scope = self._language_scope(query.language)
            return f"{self.base_url}/{scope}/{HOMES_OPTIONS}/subtitles/{resource}.json"
        return f"{self.base_url}/subtitles/{resource}.json"

    def _language_scope(self, language: str | None) -> str:
        # A requested language is scoped to itself + English: the add-on
        # accepts at most 10 languages and returns a limited result set, so a
        # broad list could push the wanted language out. No preference keeps
        # the broad default set.
        if language:
            codes = [language]
            if language != "en":
                codes.append("en")
            return "|".join(codes)
        return "|".join(self.default_languages[:10])

    def _parse(self, entry: dict) -> Subtitle:
        code = normalize_language(
            entry.get("lang_code") or entry.get("lang") or entry.get("language")
        ) or ""
        title = ""
        for key in ("title", "subtitleFileName", "movieReleaseName"):
            value = entry.get(key)
            if isinstance(value, str) and value.strip():
                title = value.strip()
                break
        url = entry.get("url") or ""
        sub_id = entry.get("sub_id") or entry.get("id") or ""
        fps = entry.get("fpsMilli")
        if isinstance(fps, (int, float)) and fps:
            fps = round(float(fps) / 1000, 3) if fps > 100 else float(fps)
        else:
            fps = None
        return Subtitle(
            url=url,
            source=self.name,
            language=code,
            label=language_label(code),
            title=title,
            fmt=guess_format(url),
            priority=self.priority,
            sub_id=str(sub_id),
            trusted=bool(entry.get("from_trusted")),
            ai_translated=bool(entry.get("ai_translated")),
            hearing_impaired=bool(
                entry.get("hearing_impaired") or entry.get("hi")
            ),
            fps=fps,
            incomplete=is_incomplete(title),
        )


class AnimeToshoProvider(SubtitleProvider):
    """Embedded fansub subtitles indexed by AnimeTosho, keyed by AniDB id."""

    name = "AnimeTosho"
    priority = 3

    def __init__(self, base_url: str, *, max_releases: int = 3, session=None):
        super().__init__(session)
        self.base_url = base_url.rstrip("/")
        self.max_releases = max_releases

    def fetch(self, query: SubtitleQuery) -> list[Subtitle]:
        if not query.anidb_id:
            return []
        releases = self._search(query.anidb_id)
        if not releases:
            return []

        exact, batch = self._rank_releases(releases, query.season, query.episode)
        candidates = exact[: self.max_releases] + batch[: self.max_releases]
        # The top exact match is trusted wholesale: single-episode releases
        # often ship a whole set of attachments whose file names don't repeat
        # the episode number.
        trusted_id = exact[0].get("id") if exact else None

        subtitles: list[Subtitle] = []
        seen: set[str] = set()
        for release in candidates:
            subtitles.extend(
                self._release_subtitles(
                    release,
                    query,
                    seen,
                    release.get("id") == trusted_id,
                )
            )
        return subtitles

    def _search(self, anidb_id: int) -> list[dict]:
        try:
            releases = self._get_json(f"{self.base_url}/json?t=search&aid={anidb_id}&max=50")
        except Exception as exc:  # noqa: BLE001
            log.warning("Subtitle source %s failed: %s", self.name, exc)
            return []
        return releases if isinstance(releases, list) else []

    def _rank_releases(self, releases: list[dict], season, episode) -> tuple[list[dict], list[dict]]:
        exact: list[dict] = []
        batch: list[dict] = []
        for release in releases:
            name = release.get("torrent_name") or release.get("title") or ""
            if matches_episode(name, episode if episode is not None else 1, season):
                exact.append(release)
            elif is_batch(name):
                batch.append(release)
        return exact, batch

    def _release_subtitles(self, release: dict, query: SubtitleQuery, seen: set[str], allow_unmatched: bool) -> list[Subtitle]:
        release_id = release.get("id")
        if not release_id:
            return []
        data = self._show(release_id)
        if not data:
            return []

        subtitles: list[Subtitle] = []
        for file in data.get("files") or []:
            name = file.get("name") or file.get("filename") or ""
            if not allow_unmatched and not matches_episode(
                name, query.episode if query.episode is not None else 1, query.season
            ):
                continue
            for attachment in file.get("attachments") or []:
                if attachment.get("type") != "subtitle":
                    continue
                url = attachment.get("url")
                if not url or url in seen:
                    continue
                seen.add(url)
                subtitles.append(self._parse_attachment(attachment, name))
        return subtitles

    def _show(self, release_id) -> dict:
        try:
            data = self._get_json(f"{self.base_url}/json?show=torrent&id={release_id}")
        except Exception as exc:  # noqa: BLE001
            log.warning("Subtitle source %s failed: %s", self.name, exc)
            return {}
        if isinstance(data, list):
            return data[0] if data else {}
        return data if isinstance(data, dict) else {}

    def _parse_attachment(self, attachment: dict, fallback_name: str) -> Subtitle:
        info = attachment.get("info") or {}
        code = normalize_language(info.get("language_code") or info.get("language")) or ""
        title = info.get("name") or fallback_name
        fmt = (info.get("format") or guess_format(attachment.get("url") or "")).lower()
        return Subtitle(
            url=attachment["url"],
            source=self.name,
            language=code,
            label=info.get("language") or language_label(code),
            title=title,
            fmt=fmt,
            priority=self.priority,
        )
