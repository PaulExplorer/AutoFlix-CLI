from curl_cffi import requests
import json
import re

from .config import portals


class AnimeExtractor:
    """
    Extracteur d'animes VO (Version Originale) basé sur CineStream.
    Cible les flux M3U8 et les lecteurs vidéo.
    """

    def __init__(self):
        # --- Source URLs loaded from source_portal.jsonc ---
        self.sudatchi_base = "https://" + portals.get("sudatchi", "sudatchi.com")
        self.animetsu_base = "https://" + portals.get("animetsu", "animetsu.live")
        self.allanime_api = (
            "https://" + portals.get("allanime-api", "api.allanime.day") + "/api"
        )
        self.allanime_referer = "https://" + portals.get(
            "allanime-referer", "allmanga.to"
        )
        self.anizone_base = "https://" + portals.get("anizone", "anizone.to")

        # Replace subdomain for animetsu API (b.animetsu.live pattern)
        self.animetsu_api = self.animetsu_base.replace("https://", "https://b.")

        self.headers = {
            "Referer": self.sudatchi_base + "/",
            "Origin": self.sudatchi_base,
        }
        self.animetsu_headers = {
            "Referer": self.animetsu_base + "/",
            "Origin": self.animetsu_base,
        }

    def _decrypt_allanime(self, hex_str):
        """Décodage simple des liens hex d'Allanime."""
        try:
            return bytes.fromhex(hex_str[2:]).decode("utf-8")
        except:
            return hex_str

    def search_sudatchi(self, anilist_id, episode=1):
        """Extraction depuis Sudatchi (M3U8 direct)."""
        base_url = self.sudatchi_base
        api_url = f"{base_url}/api/episode/{anilist_id}/{episode}"

        try:
            response = requests.get(
                api_url, headers=self.headers, timeout=10, impersonate="chrome"
            )
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
        api_url = self.allanime_api
        referer = self.allanime_referer

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
                impersonate="chrome",
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
                impersonate="chrome",
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
        base_url = self.anizone_base
        try:
            # 1. Recherche
            r = requests.get(
                f"{base_url}/anime?search={title}",
                headers=self.headers,
                timeout=10,
                impersonate="chrome",
            )
            match = re.search(r'href="(https://anizone\.to/anime/[^"]+)"', r.text)
            if not match:
                return []

            # 2. Episode
            ep_url = f"{match.group(1)}/{episode}"
            r = requests.get(
                ep_url,
                headers=self.headers,
                timeout=10,
                impersonate="chrome",
            )
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

    def search_animetsu(self, title, anilist_id, episode=1):
        """Extraction depuis Animetsu (Gojo)."""
        if not anilist_id:
            return []
        try:
            # 1. Recherche
            r = requests.get(
                f"{self.animetsu_api}/api/anime/search/?query={title}",
                headers=self.animetsu_headers,
                timeout=10,
                impersonate="chrome",
            )
            results = r.json().get("results", [])
            gojo_id = next(
                (
                    item["id"]
                    for item in results
                    if item.get("anilist_id") == anilist_id
                ),
                None,
            )
            if not gojo_id:
                return []

            # 2. Serveurs
            r = requests.get(
                f"{self.animetsu_api}/api/anime/servers/{gojo_id}/{episode}",
                headers=self.animetsu_headers,
                timeout=10,
                impersonate="chrome",
            )
            servers_data = r.json()

            results = []
            for server_obj in servers_data:
                server_id = server_obj.get("id")
                if not server_id:
                    continue

                for lang in ["sub", "dub"]:
                    try:
                        r = requests.get(
                            f"{self.animetsu_api}/api/anime/oppai/{gojo_id}/{episode}?server={server_id}&source_type={lang}",
                            headers=self.animetsu_headers,
                            timeout=10,
                            impersonate="chrome",
                        )
                        stream_data = r.json()
                        sources = stream_data.get("sources", [])

                        # Softsubs extraction
                        subs = []
                        for sub in stream_data.get("subtitles", []):
                            subs.append(
                                {"lang": sub.get("lang"), "url": sub.get("url")}
                            )

                        for src in sources:
                            url = src.get("url")
                            if not url:
                                continue
                            # Animetsu utilise un proxy
                            if not url.startswith("http"):
                                url = f"https://ani.metsu.site/proxy/{url.lstrip('/')}"

                            results.append(
                                {
                                    "source": f"Animetsu ({lang.upper()} - {server_id})",
                                    "quality": src.get("quality", "1080p"),
                                    "url": url,
                                    "type": (
                                        "M3U8"
                                        if src.get("type") != "video/mp4"
                                        else "MP4"
                                    ),
                                    "subtitles": subs if subs else None,
                                }
                            )
                    except:
                        continue
            return results
        except:
            return []

    def extract_vo(self, title=None, anilist_id=None, episode=1):
        """Recherche, déduplication et tri."""
        results = []
        if anilist_id:
            results.extend(self.search_sudatchi(anilist_id, episode))
        if title:
            results.extend(self.search_allanime(title, episode))
            results.extend(self.search_anizone(title, episode))

        if title and anilist_id:
            results.extend(self.search_animetsu(title, anilist_id, episode))

        # Déduplication simple par URL
        unique = {}
        for r in results:
            if r["url"] not in unique:
                unique[r["url"]] = r
        return list(unique.values())


# Instantiate a global instance for easy use
goldenanime = AnimeExtractor()
