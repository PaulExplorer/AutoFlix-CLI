import re
from urllib.parse import quote
from curl_cffi import requests as cffi_requests
from .config import portals
from ..proxy import DNS_OPTIONS

scraper = cffi_requests.Session(impersonate="chrome", curl_options=DNS_OPTIONS)

# Public player key embedded in MoviesAPI's own web player JS (de-facto public).
MOVIESAPI_KEY = (
    "3a67e8866ae1d2bb9e81fe7f73315a56eb3bdf5e3e755c7554c8be6910aa6b13"
)

# Videasy hosted API (CineStream's backend) + player origin used by its CDNs.
VIDEASY_ORIGIN = "https://player.videasy.to"
VIDEASY_SERVERS = [
    "downloader2",
    "m4uhd",
    "cdn",
    "lamovie",
    "superflix",
    "hdmovie",
]


class MediaExtractor:
    """
    Movie and Series extractor based on CineStream.
    Targets M3U8 streams and video players.
    """

    def __init__(self):
        # --- Source URLs loaded from source_portal.jsonc ---
        self.xpass_api = portals.get("xpass", "https://play.xpass.top")
        self.moviesapi_api = portals.get("moviesapi", "https://moviesapi.to")
        self.videasy_api = portals.get("videasy", "https://api.speedracelight.com")

    def search_moviesapi(self, tmdb_id, season=None, episode=None):
        """Extraction via MoviesAPI (Vidora backend). Direct HLS by TMDB ID."""
        if not tmdb_id:
            return []
        try:
            headers = {
                "x-player-key": MOVIESAPI_KEY,
                "Accept": "application/json, text/plain, */*",
                "User-Agent": scraper.headers.get("User-Agent", "Mozilla/5.0"),
                "Referer": f"{self.moviesapi_api}/",
                "Origin": self.moviesapi_api,
                "Sec-Fetch-Dest": "empty",
                "Sec-Fetch-Mode": "cors",
                "Sec-Fetch-Site": "same-origin",
            }

            if season is None:
                path = f"/api/vidora/v1/movie/{tmdb_id}"
            else:
                path = f"/api/vidora/v1/tv/{tmdb_id}/{season}/{episode}"

            r = scraper.get(
                f"{self.moviesapi_api}{path}", headers=headers, timeout=15
            )
            if r.status_code != 200:
                return []
            data = r.json()
            if not data.get("result") or not data.get("sources"):
                return []

            source = data["sources"][0]
            stream_url = source.get("url")
            if not stream_url:
                return []

            cdn_headers = {
                "Referer": f"{self.moviesapi_api}/",
                "Origin": self.moviesapi_api,
            }
            subtitles = [
                {
                    "lang": t.get("label") or t.get("language") or "?",
                    "url": t["file"],
                    "headers": cdn_headers,
                }
                for t in (source.get("tracks") or [])
                if t.get("file")
            ]
            return [
                {
                    "source": "MoviesAPI",
                    "quality": "Auto",
                    "url": stream_url,
                    "type": "M3U8",
                    "subtitles": subtitles or None,
                    "headers": cdn_headers,
                }
            ]
        except:
            return []

    def search_videasy(
        self,
        tmdb_id,
        title=None,
        year=None,
        imdb_id=None,
        season=None,
        episode=None,
    ):
        """Extraction via Videasy hosted API (api.speedracelight.com).

        Multi-server backend: seed -> per-server encrypted payload -> decrypt
        through enc-dec.app. Returns real MP4/HLS links with VTT subtitles.
        """
        if not tmdb_id:
            return []

        api = self.videasy_api
        try:
            headers = {
                "Accept": "*/*",
                "User-Agent": scraper.headers.get("User-Agent", "Mozilla/5.0"),
                "Origin": VIDEASY_ORIGIN,
                "Referer": f"{VIDEASY_ORIGIN}/",
            }

            r = scraper.get(
                f"{api}/seed?mediaId={tmdb_id}", headers=headers, timeout=10
            )
            if r.status_code != 200:
                return []
            seed = r.json().get("seed")
            if not seed:
                return []

            enc_title = quote(quote(title or ""))
            query = [
                f"title={enc_title}",
                f"mediaType={'tv' if season is not None else 'movie'}",
                f"tmdbId={tmdb_id}",
                "enc=2",
                f"seed={seed}",
            ]
            if year:
                query.append(f"year={year}")
            if imdb_id:
                query.append(f"imdbId={imdb_id}")
            if season is not None:
                query.append(f"seasonId={season}")
            if episode is not None:
                query.append(f"episodeId={episode}")
            query_string = "&".join(query)

            cdn_headers = {"Referer": f"{VIDEASY_ORIGIN}/"}
            results = []
            seen = set()

            for server in VIDEASY_SERVERS:
                try:
                    r = scraper.get(
                        f"{api}/{server}/sources-with-title?{query_string}",
                        headers=headers,
                        timeout=12,
                    )
                    if r.status_code != 200:
                        continue
                    j = scraper.post(
                        "https://enc-dec.app/api/dec-videasy",
                        json={"text": r.text, "id": tmdb_id, "seed": seed},
                        timeout=15,
                    )
                    if j.status_code != 200:
                        continue
                    payload = j.json().get("result") or {}
                    subtitles = [
                        {
                            "lang": t.get("language") or t.get("label") or "?",
                            "url": t["url"],
                            "headers": cdn_headers,
                        }
                        for t in (payload.get("subtitles") or [])
                        if t.get("url")
                    ]
                    for src in payload.get("sources") or []:
                        url = src.get("url")
                        if url and url not in seen:
                            seen.add(url)
                            results.append(
                                {
                                    "source": "Videasy",
                                    "quality": src.get("quality") or "Auto",
                                    "url": url,
                                    "type": (
                                        "M3U8"
                                        if "m3u8" in url.lower()
                                        else "VIDEO"
                                    ),
                                    "subtitles": subtitles or None,
                                    "headers": cdn_headers,
                                }
                            )
                            if len(results) >= 10:
                                return results
                except:
                    continue
            return results
        except:
            return []

    def search_xpass(self, tmdb_id, season=None, episode=None):
        """Extraction via Xpass."""
        if not tmdb_id:
            return []

        base_url = self.xpass_api
        try:
            embed_url = (
                f"{base_url}/e/movie/{tmdb_id}"
                if season is None
                else f"{base_url}/e/tv/{tmdb_id}/{season}/{episode}"
            )
            r = scraper.get(embed_url, headers={"Referer": f"{base_url}/"}, timeout=10)

            # Extract backups/sources via regex (deduplicated, capped)
            matches = []
            for m in re.findall(
                r'"(?:url|playlist)"\s*:\s*"([^"]+playlist\.json)"', r.text
            ):
                if m not in matches:
                    matches.append(m)
            results = []

            for url in matches[:8]:
                full_url = url if url.startswith("http") else f"{base_url}{url}"
                try:
                    r_json = scraper.get(full_url, timeout=6).json()
                    playlist = r_json.get("playlist", [])[0]
                    sources = playlist.get("sources", [])
                    for src in sources:
                        file_url = src.get("file")
                        if file_url:
                            results.append(
                                {
                                    "source": "Xpass",
                                    "quality": "Multi",
                                    "url": file_url,
                                    "type": (
                                        "M3U8"
                                        if "m3u8" in file_url.lower()
                                        else "VIDEO"
                                    ),
                                    "headers": {"Referer": f"{base_url}/"},
                                }
                            )
                except:
                    continue
            return results
        except:
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
        """Main search method."""
        results = []

        # Priority: MoviesAPI (hosted API, fast single request), then Xpass
        # as fallback for titles not encoded on Vidora.
        # VidLink is parsed but excluded: its MP4 CDN (bcdn.hakunaymatata.com)
        # requires a proxy (requiresProxy=True) and blocks direct access (403/429).
        # Mapple is dead: every source returns the same signed URL on
        # source.heistotron.uk serving a 26s loading clip instead of the media.
        if tmdb_id:
            results.extend(self.search_moviesapi(tmdb_id, season, episode))
            results.extend(
                self.search_videasy(
                    tmdb_id, title, year, imdb_id, season, episode
                )
            )
            results.extend(self.search_xpass(tmdb_id, season, episode))

        # Deduplication by URL
        unique = {}
        for r in results:
            if r["url"] and r["url"] not in unique:
                unique[r["url"]] = r
        return list(unique.values())


# Instantiate a global instance for easy use
goldenms_extractor = MediaExtractor()
