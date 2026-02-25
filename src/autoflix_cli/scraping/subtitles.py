from curl_cffi import requests
import random


class SubtitleExtractor:
    """
    Subtitle extractor optimized to be used as a library.
    Results are sorted by order of confidence (OpenSubtitles > WYZIE > Subsense).
    """

    # Order of confidence of sources (lower = higher in the list)
    SOURCE_PRIORITY = {"OpenSubtitles (Stremio)": 1, "WYZIE": 2, "Subsense": 3}

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
        except Exception as e:
            # In library mode, we stay discreet about network errors
            return []

    def get_opensubtitles_stremio(self, imdb_id, season=None, episode=None):
        """OpenSubtitles via Stremio bridge (French support included)."""
        # Using OpenSubtitles v3
        base_url = "https://opensubtitles-v3.strem.io"
        subs = self._fetch_stremio(base_url, imdb_id, season, episode)
        for s in subs:
            s["source"] = "OpenSubtitles (Stremio)"
        return subs

    def get_subsense(self, imdb_id, season=None, episode=None):
        """Subsense via Stremio bridge (French support included)."""
        # Adding 'fr' to the config
        config = (
            'n0tcjfba-{"languages":["en","fr","hi","ta","es","ar"],"maxSubtitles":10}'
        )
        base_url = f"https://subsense.nepiraw.com/{config}"
        subs = self._fetch_stremio(base_url, imdb_id, season, episode)
        for s in subs:
            s["source"] = "Subsense"
        return subs

    def get_wyzie(self, imdb_id, season=None, episode=None):
        """WYZIE Subtitles API."""
        base_url = "https://sub.wyzie.ru"
        url = f"{base_url}/search?id={imdb_id}"
        if season and episode:
            url += f"&season={season}&episode={episode}"

        try:
            response = requests.get(url, timeout=10, impersonate="chrome")
            response.raise_for_status()
            data = response.json()
            normalized = []
            for item in data:
                normalized.append(
                    {
                        "lang": item.get("display") or item.get("language"),
                        "url": item.get("url"),
                        "source": "WYZIE",
                    }
                )
            return normalized
        except:
            return []

    def search(self, imdb_id, season=None, episode=None, lang_filter=None):
        """
        Search, filter and sort subtitles by order of confidence.
        :param lang_filter: Language code or name (e.g., 'French', 'fr').
        :return: Sorted list of dictionaries.
        """
        all_subs = []
        all_subs.extend(self.get_opensubtitles_stremio(imdb_id, season, episode))
        all_subs.extend(self.get_wyzie(imdb_id, season, episode))
        all_subs.extend(self.get_subsense(imdb_id, season, episode))

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

        # 2. Sort by source priority (OpenSubs > WYZIE > Subsense)
        # First shuffle to have a random order between links from the same source
        random.shuffle(all_subs)
        all_subs.sort(key=lambda x: self.SOURCE_PRIORITY.get(x["source"], 99))
        return all_subs


# Instantiate a global instance for easy use
subtitle_extractor = SubtitleExtractor()
