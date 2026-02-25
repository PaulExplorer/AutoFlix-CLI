from curl_cffi import requests
import json
import re

from .config import portals


class AnimeExtractor:
    """
    Original Version (VO) anime extractor based on CineStream.
    Targets M3U8 streams and video players.
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
        """Simple decoding of Allanime hex links."""
        try:
            return bytes.fromhex(hex_str[2:]).decode("utf-8")
        except:
            return hex_str

    def search_sudatchi(self, anilist_id, episode=1):
        """Extraction from Sudatchi (direct M3U8)."""
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

            # The stream link is an API call that often returns the M3U8
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
        """Extraction from Allanime using GQL hashes."""
        api_url = self.allanime_api
        referer = self.allanime_referer

        # GQL Hashes (CineStream)
        search_hash = "06327bc10dd682e1ee7e07b6db9c16e9ad2fd56c1b769e47513128cd5c9fc77a"
        ep_hash = "5f1a64b73793cc2234a389cf3a8f93ad82de7043017dd551f38f65b89daa65e0"

        try:
            # 1. Search
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

            # 1.1 Match title
            show_id = None
            if title:
                t_lower = title.lower().strip()
                for edge in shows:
                    name = (edge.get("name") or "").lower().strip()
                    eng = (edge.get("englishName") or "").lower().strip()
                    if name == t_lower or eng == t_lower:
                        show_id = edge.get("_id")
                        break

                if not show_id:
                    # Fallback to fuzzy: find result that contains title AND doesn't have "Season"
                    # unless title itself has "Season"
                    has_season_query = "season" in t_lower or "saison" in t_lower
                    for edge in shows:
                        name = (edge.get("name") or "").lower().strip()
                        eng = (edge.get("englishName") or "").lower().strip()
                        if t_lower in name or t_lower in eng:
                            if not has_season_query:
                                if "season" not in name and "season" not in eng:
                                    show_id = edge.get("_id")
                                    break
                            else:
                                show_id = edge.get("_id")
                                break

            if not show_id and shows:
                show_id = shows[0].get("_id")

            if not show_id:
                return []

            # 2. Links
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
        """Extraction from Anizone (Regex used to avoid bs4 dependency)."""
        base_url = self.anizone_base
        try:
            # 1. Search
            r = requests.get(
                f"{base_url}/anime?search={title}",
                headers=self.headers,
                timeout=10,
                impersonate="chrome",
            )

            # Find all relevant matches
            matches = re.finditer(r'href="(https://anizone\.to/anime/([^"]+))"', r.text)
            best_url = None

            if title:
                t_slug = title.lower().replace(" ", "-")
                for m in matches:
                    full_url = m.group(1)
                    slug = m.group(2)
                    if not best_url:
                        best_url = full_url  # Fallback to first
                    if slug == t_slug:
                        best_url = full_url
                        break
                    if t_slug in slug and "season" not in slug:
                        best_url = full_url

            if not best_url:
                match = re.search(r'href="(https://anizone\.to/anime/[^"]+)"', r.text)
                if match:
                    best_url = match.group(1)

            if not best_url:
                return []

            # 2. Episode
            ep_url = f"{best_url}/{episode}"
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
        """Extraction from Animetsu (Gojo)."""
        if not anilist_id:
            return []
        try:
            # 1. Search
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

            # 2. Servers
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

                        # Extract softsubs
                        subs = []
                        for sub in stream_data.get("subtitles", []):
                            subs.append(
                                {"lang": sub.get("lang"), "url": sub.get("url")}
                            )

                        for src in sources:
                            url = src.get("url")
                            if not url:
                                continue
                            # Animetsu uses a proxy
                            if not url.startswith("http"):
                                url = f"https://ani.metsu.site/proxy/{url.lstrip('/')}"

                            player = {
                                "source": f"Animetsu ({lang.upper()} - {server_id})",
                                "quality": src.get("quality", "1080p"),
                                "url": url,
                                "type": (
                                    "M3U8" if src.get("type") != "video/mp4" else "MP4"
                                ),
                                "subtitles": subs if subs else None,
                            }

                            if (
                                server_id == "kite" or server_id == "zoro"
                            ) and lang.upper() == "SUB":
                                results.insert(0, player)
                            else:
                                results.append(player)
                    except:
                        continue
            return results
        except:
            return []

    def extract_vo(self, title=None, anilist_id=None, episode=1):
        """Search, deduplication, and sorting."""
        results = []

        if anilist_id:
            results.extend(self.search_sudatchi(anilist_id, episode))
        if title:
            results.extend(self.search_anizone(title, episode))
        if title and anilist_id:
            results.extend(self.search_animetsu(title, anilist_id, episode))
        if title:
            results.extend(self.search_allanime(title, episode))

        # Simple deduplication by URL
        unique = {}
        for r in results:
            if r["url"] not in unique:
                unique[r["url"]] = r
        return list(unique.values())


# Instantiate a global instance for easy use
goldenanime = AnimeExtractor()
