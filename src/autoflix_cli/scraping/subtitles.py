from curl_cffi import requests
import random


class SubtitleExtractor:
    """
    Extracteur de sous-titres optimisé pour être utilisé comme bibliothèque.
    Les résultats sont triés par ordre de confiance (OpenSubtitles > Subsense > WYZIE).
    """

    # Ordre de confiance des sources (plus bas = plus haut dans la liste)
    SOURCE_PRIORITY = {"OpenSubtitles (Stremio)": 1, "Subsense": 2, "WYZIE": 3}

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
            # En mode bibliothèque, on reste discret sur les erreurs réseau
            return []

    def get_opensubtitles_stremio(self, imdb_id, season=None, episode=None):
        """OpenSubtitles via Stremio bridge (Support français inclus)."""
        # Ajout de 'fr' à la liste des langues demandées
        base_url = "https://opensubtitles.stremio.homes/en|fr|hi|de|ar|tr|es|ta|te|ru|ko/ai-translated=true|from=all|auto-adjustment=true"
        subs = self._fetch_stremio(base_url, imdb_id, season, episode)
        for s in subs:
            s["source"] = "OpenSubtitles (Stremio)"
        return subs

    def get_subsense(self, imdb_id, season=None, episode=None):
        """Subsense via Stremio bridge (Support français inclus)."""
        # Ajout de 'fr' à la config
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
        Recherche, filtre et trie les sous-titres par ordre de confiance.
        :param lang_filter: Code langue ou nom (ex: 'French', 'fr').
        :return: Liste de dictionnaires triée.
        """
        all_subs = []
        all_subs.extend(self.get_opensubtitles_stremio(imdb_id, season, episode))
        all_subs.extend(self.get_subsense(imdb_id, season, episode))
        all_subs.extend(self.get_wyzie(imdb_id, season, episode))

        # 1. Filtrage par langue (insensible à la casse)
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

        # 2. Tri par priorité de source (OpenSubs > Subsense > WYZIE)
        # On mélange d'abord pour avoir un ordre aléatoire entre les liens d'une même source
        random.shuffle(all_subs)
        all_subs.sort(key=lambda x: self.SOURCE_PRIORITY.get(x["source"], 99))
        return all_subs


# Instantiate a global instance for easy use
subtitle_extractor = SubtitleExtractor()
