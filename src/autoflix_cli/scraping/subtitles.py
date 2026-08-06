from curl_cffi import requests
import random
import re

from .config import portals


class SubtitleExtractor:
    """
    Subtitle extractor optimized to be used as a library.
    Results are sorted by order of confidence (OpenSubtitles > AnimeTosho).
    """

    # Order of confidence of sources (lower = higher in the list)
    SOURCE_PRIORITY = {
        "OpenSubtitles (Stremio)": 1,
        "AnimeTosho": 2,
    }

    def _fetch_stremio(self, base_url, imdb_id, season=None, episode=None):
        """Helper for Stremio-style subtitle APIs."""
        if season and episode:
            endpoint = f"{base_url}/subtitles/series/{imdb_id}:{season}:{episode}.json"
        else:
            endpoint = f"{base_url}/subtitles/movie/{imdb_id}.json"

        try:
            response = requests.get(endpoint, timeout=10, impersonate="chrome")
            response.raise_for_status()
            data = response.json()
            return data.get("subtitles", [])
        except Exception:
            return []

    def get_opensubtitles_stremio(self, imdb_id, season=None, episode=None):
        """OpenSubtitles via Stremio bridge (French support included)."""
        base_url = "https://opensubtitles-v3.strem.io"
        subs = self._fetch_stremio(base_url, imdb_id, season, episode)
        for s in subs:
            s["source"] = "OpenSubtitles (Stremio)"
        return subs

    @staticmethod
    def _matches_episode(name, episode, season=None):
        """Heuristic match of a release/file name against an episode number."""
        name = name.lower()
        ep = str(episode).zfill(2)
        ep_plain = str(episode)

        if season:
            # Prefer explicit SxxEyy patterns (e.g. s01e05, 1x05)
            season_tokens = [str(season).zfill(2), str(season)]
            for s in season_tokens:
                for e in (ep, ep_plain):
                    if re.search(rf"\b(?:s|season\s*){s}[ex]{e}\b", name):
                        return True
                    if re.search(rf"{s}x{e}\b", name):
                        return True

        # Bare episode token, e.g. " - 01 -", "[01]", "ep05"
        if re.search(rf"(?<!\d){ep}(?!\d)", name):
            return True
        if re.search(rf"(?<!\d){ep_plain}(?!\d)", name):
            return True
        if re.search(rf"\bep(?:isode\s*)?{ep}\b", name):
            return True
        return False

    @staticmethod
    def _is_batch(name):
        name = name.lower()
        return bool(re.search(r"\bs\d{1,2}\b", name)) or any(
            tag in name for tag in ("batch", "complete", "collection")
        )

    def get_animetosho(self, anidb_id, episode, season=None, max_releases=3):
        """
        Subtitles extracted from AnimeTosho releases (fansub EN/ASS).

        AnimeTosho indexes releases by AniDB ID and exposes the embedded
        subtitles of each file as direct download links (``.xz`` compressed).
        """
        base = portals.get("animetosho", "https://feed.animetosho.xyz")
        try:
            r = requests.get(
                f"{base}/json?t=search&aid={anidb_id}&max=50",
                timeout=15,
                impersonate="chrome",
            )
            r.raise_for_status()
            releases = r.json()
        except Exception:
            return []

        if not isinstance(releases, list):
            return []

        # Rank candidates: exact episode match first, then episode-in-batch
        exact = []
        batch = []
        for rel in releases:
            name = rel.get("torrent_name") or rel.get("title") or ""
            if self._matches_episode(name, episode, season):
                exact.append(rel)
            elif self._is_batch(name):
                batch.append(rel)

        candidates = (exact or batch)[:max_releases]

        subs = []
        seen = set()
        for rel in candidates:
            rid = rel.get("id")
            if not rid:
                continue
            try:
                r = requests.get(
                    f"{base}/json?show=torrent&id={rid}",
                    timeout=15,
                    impersonate="chrome",
                )
                r.raise_for_status()
                data = r.json()
                if isinstance(data, list):
                    data = data[0] if data else {}
            except Exception:
                continue

            for f in data.get("files") or []:
                fname = f.get("name") or f.get("filename") or ""
                file_matches = self._matches_episode(fname, episode, season)
                if not file_matches and not (exact and rel in exact[:1]):
                    continue

                for att in f.get("attachments") or []:
                    if att.get("type") != "subtitle":
                        continue
                    url = att.get("url")
                    if not url or url in seen:
                        continue
                    info = att.get("info") or {}
                    seen.add(url)
                    subs.append(
                        {
                            "lang": info.get("language_code") or "en",
                            "label": info.get("language") or "English",
                            "format": info.get("format") or "ASS",
                            "url": url,
                            "source": "AnimeTosho",
                        }
                    )
        return subs

    def search(
        self,
        imdb_id,
        season=None,
        episode=None,
        lang_filter=None,
        anidb_id=None,
    ):
        """
        Search, filter and sort subtitles by order of confidence.
        :param lang_filter: Language code or name (e.g., 'French', 'fr').
        :param anidb_id: AniDB ID used by AnimeTosho (optional).
        :return: Sorted list of dictionaries.
        """
        all_subs = []
        all_subs.extend(self.get_opensubtitles_stremio(imdb_id, season, episode))
        if anidb_id:
            all_subs.extend(
                self.get_animetosho(anidb_id, episode=episode or 1, season=season)
            )

        # 1. Filter by language (case insensitive)
        if lang_filter:
            f = lang_filter.lower()
            # Dynamic mapping from languages.py
            from ..languages import get_language_aliases

            aliases = get_language_aliases()
            target = aliases.get(f, f)

            filtered = []
            for sub in all_subs:
                l = (sub.get("lang") or sub.get("lang_code") or "").lower()
                if target in l or l in target or (len(f) == 2 and l.startswith(f)):
                    filtered.append(sub)
            all_subs = filtered

        # 2. Sort by source priority (OpenSubtitles > AnimeTosho)
        # First shuffle to have a random order between links from the same source
        random.shuffle(all_subs)
        all_subs.sort(key=lambda x: self.SOURCE_PRIORITY.get(x["source"], 99))
        return all_subs


# Instantiate a global instance for easy use
subtitle_extractor = SubtitleExtractor()
