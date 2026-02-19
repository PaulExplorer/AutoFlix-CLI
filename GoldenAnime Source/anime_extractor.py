#!/usr/bin/env python3
import requests
import json
import argparse
import sys
import re


class AnimeExtractor:
    """
    Extracteur d'animes VO (Version Originale) basé sur CineStream.
    Cible les flux M3U8 et les lecteurs vidéo.
    """

    def __init__(self):
        self.user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        self.headers = {
            "User-Agent": self.user_agent,
            "Referer": "https://sudatchi.com/",
            "Origin": "https://sudatchi.com",
        }

    def _decrypt_allanime(self, hex_str):
        """Décodage simple des liens hex d'Allanime."""
        try:
            return bytes.fromhex(hex_str[2:]).decode("utf-8")
        except:
            return hex_str

    def search_sudatchi(self, anilist_id, episode=1):
        """Extraction depuis Sudatchi (M3U8 direct)."""
        base_url = "https://sudatchi.com"
        api_url = f"{base_url}/api/episode/{anilist_id}/{episode}"

        try:
            response = requests.get(api_url, headers=self.headers, timeout=10)
            if response.status_code != 200:
                return []

            data = response.json()
            ep_id = data.get("episode", {}).get("id")
            if not ep_id:
                return []

            # Le lien de stream est un appel API qui renvoie souvent le M3U8
            stream_url = f"{base_url}/api/streams?episodeId={ep_id}"

            return [
                {
                    "source": "Sudatchi",
                    "quality": "1080p",
                    "url": stream_url,
                    "type": "M3U8",
                }
            ]
        except Exception as e:
            return []

    def search_allanime(self, title, episode=1):
        """Extraction depuis Allanime avec hashes GQL."""
        api_url = "https://api.allanime.day/api"
        referer = "https://allmanga.to"

        # Hashs GQL (CineStream)
        search_hash = "06327bc10dd682e1ee7e07b6db9c16e9ad2fd56c1b769e47513128cd5c9fc77a"
        ep_hash = "5f1a64b73793cc2234a389cf3a8f93ad82de7043017dd551f38f65b89daa65e0"

        try:
            # 1. Recherche
            vars_search = {
                "search": {"query": title, "types": ["TV", "Movie"]},
                "limit": 26,
                "page": 1,
                "translationType": "sub",
                "countryOrigin": "ALL",
            }
            ext_search = {"persistedQuery": {"version": 1, "sha256Hash": search_hash}}

            r = requests.get(
                api_url,
                params={
                    "variables": json.dumps(vars_search),
                    "extensions": json.dumps(ext_search),
                },
                headers={"Referer": referer},
                timeout=10,
            )
            shows = r.json().get("data", {}).get("shows", {}).get("edges", [])
            if not shows:
                return []

            show_id = shows[0].get("_id")

            # 2. Liens
            vars_ep = {
                "showId": show_id,
                "translationType": "sub",
                "episodeString": str(episode),
            }
            ext_ep = {"persistedQuery": {"version": 1, "sha256Hash": ep_hash}}

            r = requests.get(
                api_url,
                params={
                    "variables": json.dumps(vars_ep),
                    "extensions": json.dumps(ext_ep),
                },
                headers={"Referer": referer},
                timeout=10,
            )
            sources = r.json().get("data", {}).get("episode", {}).get("sourceUrls", [])

            results = []
            for src in sources:
                url = src.get("sourceUrl")
                if url.startswith("--"):
                    url = self._decrypt_allanime(url)
                if not url.startswith("http"):
                    continue

                results.append(
                    {
                        "source": f"Allanime ({src.get('sourceName', 'Default')})",
                        "quality": "Multi",
                        "url": url,
                        "type": "Player/M3U8",
                    }
                )
            return results
        except:
            return []

    def search_anizone(self, title, episode=1):
        """Extraction depuis Anizone (Regex pour éviter bs4 dependency)."""
        base_url = "https://anizone.to"
        try:
            # 1. Recherche
            r = requests.get(
                f"{base_url}/anime?search={title}", headers=self.headers, timeout=10
            )
            match = re.search(r'href="(https://anizone\.to/anime/[^"]+)"', r.text)
            if not match:
                return []

            # 2. Episode
            ep_url = f"{match.group(1)}/{episode}"
            r = requests.get(ep_url, headers=self.headers, timeout=10)
            player_match = re.search(r'<media-player[^>]+src="([^"]+)"', r.text)

            if player_match:
                return [
                    {
                        "source": "Anizone",
                        "quality": "1080p",
                        "url": player_match.group(1),
                        "type": "M3U8",
                    }
                ]
        except:
            pass
        return []

    def extract_vo(self, title=None, anilist_id=None, episode=1):
        """Recherche, déduplication et tri."""
        results = []
        if anilist_id:
            results.extend(self.search_sudatchi(anilist_id, episode))
        if title:
            results.extend(self.search_allanime(title, episode))
            results.extend(self.search_anizone(title, episode))

        # Déduplication simple par URL
        unique = {}
        for r in results:
            if r["url"] not in unique:
                unique[r["url"]] = r
        return list(unique.values())


def main():
    parser = argparse.ArgumentParser(
        description="Extract Anime VO streams from CineStream sources."
    )
    parser.add_argument("title", nargs="?", help="Anime title for search")
    parser.add_argument(
        "--anilist", type=int, help="AniList ID (highly recommended for Sudatchi)"
    )
    parser.add_argument("-e", "--episode", type=int, default=1, help="Episode number")

    args = parser.parse_args()

    if not args.title and not args.anilist:
        print("Error: Provide either a title or an AniList ID.")
        sys.exit(1)

    extractor = AnimeExtractor()
    results = extractor.extract_vo(
        title=args.title, anilist_id=args.anilist, episode=args.episode
    )

    if not results:
        print("No VO streams found.")
        return

    print(f"\nFound {len(results)} VO streams for ep {args.episode}:\n")
    print(f"{'Source':<30} | {'Quality':<10} | {'URL'}")
    print("-" * 100)
    for res in results:
        print(f"{res['source']:<30} | {res['quality']:<10} | {res['url']}")


if __name__ == "__main__":
    main()
