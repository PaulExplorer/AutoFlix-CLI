#!/usr/bin/env python3
import requests
import json
import argparse
import sys
import re
import urllib.parse


class MediaExtractor:
    """
    Extracteur de Films et Séries basé sur CineStream.
    Cible les flux M3U8 et les lecteurs vidéo.
    """

    def __init__(self):
        self.user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        self.multi_decrypt_api = "https://enc-dec.app/api"
        self.videasy_api = "https://api.videasy.net"
        self.vidlink_api = "https://vidlink.pro"
        self.hexa_api = "https://themoviedb.hexa.su"

        self.headers = {"User-Agent": self.user_agent, "Connection": "keep-alive"}

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

                r = requests.get(url, headers=self.headers, timeout=10)
                enc_data = r.text

                # Décryptage
                payload = {"text": enc_data, "id": str(tmdb_id) if tmdb_id else ""}
                r_dec = requests.post(
                    f"{self.multi_decrypt_api}/dec-videasy", json=payload, timeout=10
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
                f"{self.multi_decrypt_api}/enc-vidlink?text={tmdb_id}", timeout=10
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

            r = requests.get(url, headers=headers, timeout=10)
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

            # Key generation (simulé car SecureRandom.nextBytes en Kotlin)
            # En fait Hexa semble exiger une clé passée au décrypteur.
            # On va utiliser une clé fixe ou aléatoire pour le header X-Api-Key si nécessaire.
            # Mais regardons le code Kotlin : il génère une clé aléatoire et la passe au POST dec-hexa.
            import secrets

            key = secrets.token_hex(32)

            headers = {**self.headers, "Accept": "plain/text", "X-Api-Key": key}

            r_enc = requests.get(url, headers=headers, timeout=10)
            enc_data = r_enc.text

            payload = {"text": enc_data, "key": key}
            r_dec = requests.post(
                f"{self.multi_decrypt_api}/dec-hexa", json=payload, timeout=10
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


def main():
    parser = argparse.ArgumentParser(
        description="Extract Movie/TV highlights (M3U8) from CineStream sources."
    )
    parser.add_argument("--title", help="Media title")
    parser.add_argument("--tmdb", type=int, help="TMDB ID")
    parser.add_argument("--imdb", help="IMDB ID")
    parser.add_argument("--year", type=int, help="Release year")
    parser.add_argument("--season", type=int, help="Season number")
    parser.add_argument("--episode", type=int, help="Episode number")
    parser.add_argument(
        "--type",
        choices=["movie", "tv"],
        default="movie",
        help="Media type (default: movie)",
    )

    args = parser.parse_args()

    if not args.title and not args.tmdb and not args.imdb:
        print("Error: Provide at least a title, TMDB ID or IMDB ID.")
        sys.exit(1)

    extractor = MediaExtractor()
    results = extractor.extract(
        title=args.title,
        tmdb_id=args.tmdb,
        imdb_id=args.imdb,
        year=args.year,
        season=args.season,
        episode=args.episode,
    )

    if not results:
        print("No streams found.")
        return

    print(f"\nFound {len(results)} streams:\n")
    print(f"{'Source':<35} | {'Quality':<10} | {'URL'}")
    print("-" * 120)
    for res in results:
        url = res["url"]
        if len(url) > 70:
            url = url[:67] + "..."
        print(f"{res['source']:<35} | {res['quality']:<10} | {url}")


if __name__ == "__main__":
    main()
