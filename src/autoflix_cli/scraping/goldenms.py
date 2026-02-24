from curl_cffi import requests
import urllib.parse
from .config import portals


class MediaExtractor:
    """
    Extracteur de Films et Séries basé sur CineStream.
    Cible les flux M3U8 et les lecteurs vidéo.
    """

    def __init__(self):
        # --- Source URLs loaded from source_portal.jsonc ---
        self.multi_decrypt_api = (
            "https://" + portals.get("multi-decrypt", "enc-dec.app") + "/api"
        )
        self.videasy_api = "https://" + portals.get("videasy", "api.videasy.net")
        self.vidlink_api = "https://" + portals.get("vidlink", "vidlink.pro")
        self.hexa_api = "https://" + portals.get("hexa", "themoviedb.hexa.su")

        self.headers = {"Connection": "keep-alive"}

    def _quote(self, text):
        return urllib.parse.quote(text).replace("+", "%20")

    def search_videasy(
        self, title, tmdb_id=None, imdb_id=None, year=None, season=None, episode=None
    ):
        """Extraction via Videasy (Multi-serveurs)."""
        servers = [
            "myflixerzupcloud",
            "1movies",
            "moviebox",
            "primewire",
            "m4uhd",
            "hdmovie",
            "cdn",
            "primesrcme",
        ]
        results = []

        if not title:
            return []

        enc_title = self._quote(self._quote(title))
        media_type = "movie" if season is None else "tv"

        for server in servers:
            try:
                url = f"{self.videasy_api}/{server}/sources-with-title?title={enc_title}&mediaType={media_type}"
                if year:
                    url += f"&year={year}"
                if tmdb_id:
                    url += f"&tmdbId={tmdb_id}"
                if imdb_id:
                    url += f"&imdbId={imdb_id}"
                if season:
                    url += f"&seasonId={season}"
                if episode:
                    url += f"&episodeId={episode}"

                r = requests.get(
                    url, headers=self.headers, timeout=10, impersonate="chrome"
                )
                enc_data = r.text

                # Décryptage
                payload = {"text": enc_data, "id": str(tmdb_id) if tmdb_id else ""}
                r_dec = requests.post(
                    f"{self.multi_decrypt_api}/dec-videasy",
                    json=payload,
                    timeout=10,
                    impersonate="chrome",
                )

                if r_dec.status_code == 200:
                    data = r_dec.json().get("result", {})
                    sources = data.get("sources", [])
                    for src in sources:
                        results.append(
                            {
                                "source": f"Videasy ({server.upper()})",
                                "quality": src.get("quality", "Multi"),
                                "url": src.get("url"),
                                "type": (
                                    "M3U8" if ".m3u8" in src.get("url", "") else "VIDEO"
                                ),
                            }
                        )
            except:
                continue
        return results

    def search_vidlink(self, tmdb_id, season=None, episode=None):
        """Extraction via Vidlink."""
        if not tmdb_id:
            return []
        try:
            # 1. Encrypt TMDB ID via API
            r_enc = requests.get(
                f"{self.multi_decrypt_api}/enc-vidlink?text={tmdb_id}",
                timeout=10,
                impersonate="chrome",
            )
            enc_data = r_enc.json().get("result")

            headers = {
                **self.headers,
                "Referer": f"{self.vidlink_api}/",
                "Origin": f"{self.vidlink_api}/",
            }

            if season is None:
                url = f"{self.vidlink_api}/api/b/movie/{enc_data}"
            else:
                url = f"{self.vidlink_api}/api/b/tv/{enc_data}/{season}/{episode}"

            r = requests.get(url, headers=headers, timeout=10, impersonate="chrome")
            data = r.json()
            m3u8_url = data.get("stream", {}).get("playlist")

            if m3u8_url:
                return [
                    {
                        "source": "Vidlink",
                        "quality": "Multi",
                        "url": m3u8_url,
                        "type": "M3U8",
                    }
                ]
        except:
            pass
        return []

    def search_hexa(self, tmdb_id, season=None, episode=None):
        """Extraction via Hexa."""
        if not tmdb_id:
            return []
        try:
            if season is None:
                url = f"{self.hexa_api}/api/tmdb/movie/{tmdb_id}/images"
            else:
                url = f"{self.hexa_api}/api/tmdb/tv/{tmdb_id}/season/{season}/episode/{episode}/images"

            import secrets

            key = secrets.token_hex(32)

            headers = {**self.headers, "Accept": "plain/text", "X-Api-Key": key}

            r_enc = requests.get(url, headers=headers, timeout=10, impersonate="chrome")
            enc_data = r_enc.text

            payload = {"text": enc_data, "key": key}
            r_dec = requests.post(
                f"{self.multi_decrypt_api}/dec-hexa",
                json=payload,
                timeout=10,
                impersonate="chrome",
            )

            if r_dec.status_code == 200:
                data = r_dec.json().get("result", {})
                sources = data.get("sources", [])
                results = []
                for src in sources:
                    results.append(
                        {
                            "source": f"Hexa ({src.get('server', '').upper()})",
                            "quality": "Multi",
                            "url": src.get("url"),
                            "type": "M3U8",
                        }
                    )
                return results
        except:
            pass
        return []

    def extract(
        self,
        title=None,
        tmdb_id=None,
        imdb_id=None,
        year=None,
        season=None,
        episode=None,
    ):
        """Méthode principale de recherche."""
        results = []

        # Priority: Vidlink, Hexa, Videasy
        if tmdb_id:
            results.extend(self.search_vidlink(tmdb_id, season, episode))
            results.extend(self.search_hexa(tmdb_id, season, episode))

        if title:
            results.extend(
                self.search_videasy(title, tmdb_id, imdb_id, year, season, episode)
            )

        # Déduplication par URL
        unique = {}
        for r in results:
            if r["url"] and r["url"] not in unique:
                unique[r["url"]] = r
        return list(unique.values())


# Instantiate a global instance for easy use
goldenms_extractor = MediaExtractor()
