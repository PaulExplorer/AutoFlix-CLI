import re
import urllib.parse
from curl_cffi import requests as cffi_requests
from .config import portals
from ..proxy import DNS_OPTIONS

scraper = cffi_requests.Session(impersonate="chrome", curl_options=DNS_OPTIONS)

# Public player key embedded in MoviesAPI's own web player JS (de-facto public).
MOVIESAPI_KEY = (
    "3a67e8866ae1d2bb9e81fe7f73315a56eb3bdf5e3e755c7554c8be6910aa6b13"
)


class MediaExtractor:
    """
    Movie and Series extractor based on CineStream.
    Targets M3U8 streams and video players.
    """

    def __init__(self):
        # --- Source URLs loaded from source_portal.jsonc ---
        self.multi_decrypt_api = portals.get(
            "multi-decrypt", "https://enc-dec.app/api"
        )
        self.videasy_api = portals.get("videasy", "https://api.videasy.net")
        self.vidlink_api = portals.get("vidlink", "https://vidlink.pro")
        self.hexa_api = portals.get("hexa", "https://themoviedb.hexa.su")
        self.mapple_api = portals.get("mapple", "https://mapple.uk")
        self.xpass_api = portals.get("xpass", "https://play.xpass.top")
        self.moviesapi_api = portals.get("moviesapi", "https://moviesapi.to")

        # --- Referers ---
        self.videasy_referer = portals.get("videasy-referer", "https://cineby.gd")
        self.hexa_referer = portals.get("hexa-referer", "https://hexa.su/")

        self.headers = {"Connection": "keep-alive"}

    def _quote(self, text):
        return urllib.parse.quote(text).replace("+", "%20")

    def search_videasy(
        self, title, tmdb_id=None, imdb_id=None, year=None, season=None, episode=None
    ):
        """Extraction via Videasy (Multi-server)."""
        headers = {
            "Accept": "*/*",
            "User-Agent": scraper.headers.get("User-Agent", "Mozilla/5.0"),
            "Origin": self.videasy_referer,
            "Referer": self.videasy_referer + "/",
        }

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

        # Double encoding as per CineStream logic
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

                r = scraper.get(url, headers=headers, timeout=10)
                if r.status_code != 200:
                    continue
                enc_data = r.text

                # Decryption via multi-decrypt (passing tmdbId as 'id')
                payload = {"text": enc_data, "id": tmdb_id}
                r_dec = scraper.post(
                    f"{self.multi_decrypt_api}/dec-videasy", json=payload, timeout=10
                )

                if r_dec.status_code == 200:
                    data = r_dec.json().get("result", {})
                    sources = data.get("sources", [])
                    subs = [
                        {"lang": s.get("language"), "url": s.get("url")}
                        for s in data.get("subtitles", [])
                    ]

                    for src in sources:
                        results.append(
                            {
                                "source": f"Videasy ({server.upper()})",
                                "quality": src.get("quality", "Multi"),
                                "url": src.get("url"),
                                "type": (
                                    "M3U8"
                                    if ".m3u8" in src.get("url", "").lower()
                                    else "VIDEO"
                                ),
                                "subtitles": subs if subs else None,
                                "headers": headers,
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
            r_enc = scraper.get(
                f"{self.multi_decrypt_api}/enc-vidlink?text={tmdb_id}", timeout=10
            )
            enc_data = r_enc.json().get("result")

            headers = {
                "User-Agent": scraper.headers.get("User-Agent", "Mozilla/5.0"),
                "Connection": "keep-alive",
                "Referer": f"{self.vidlink_api}/",
                "Origin": self.vidlink_api,
            }

            if season is None:
                url = f"{self.vidlink_api}/api/b/movie/{enc_data}"
            else:
                url = f"{self.vidlink_api}/api/b/tv/{enc_data}/{season}/{episode}"

            r = scraper.get(url, headers=headers, timeout=10)
            data = r.json()
            stream = data.get("stream", {})

            subtitles = None
            captions = stream.get("captions") or []
            if captions:
                subtitles = [
                    {"lang": c.get("language", "?"), "url": c.get("url")}
                    for c in captions
                    if c.get("url")
                ]

            qualities = stream.get("qualities") or {}
            m3u8_url = stream.get("playlist") or (qualities or {}).get("master")

            results = []
            if m3u8_url:
                results.append(
                    {
                        "source": "Vidlink",
                        "quality": "Multi",
                        "url": m3u8_url,
                        "type": "M3U8",
                        "subtitles": subtitles,
                        "headers": headers,
                    }
                )
            else:
                for quality in ("1080", "720", "480", "360"):
                    if quality in qualities:
                        q = qualities[quality]
                        results.append(
                            {
                                "source": "Vidlink",
                                "quality": f"{quality}p",
                                "url": q.get("url"),
                                "type": q.get("type", "MP4").upper(),
                                "subtitles": subtitles,
                                "headers": headers,
                            }
                        )

            return results
        except:
            pass
        return []

    def search_hexa(self, tmdb_id, season=None, episode=None):
        """Extraction via Hexa with dynamic security handshake."""
        if not tmdb_id:
            return []
        try:
            # 1. Endpoint
            if season is None:
                url = f"{self.hexa_api}/api/tmdb/movie/{tmdb_id}/images"
            else:
                url = f"{self.hexa_api}/api/tmdb/tv/{tmdb_id}/season/{season}/episode/{episode}/images"

            # 2. Security Handshake
            import secrets

            key = secrets.token_hex(32)  # Generate 32-byte key

            # Fetch X-Cap-Token from multi-decrypt
            r_token = scraper.get(f"{self.multi_decrypt_api}/enc-hexa", timeout=10)
            cap_token = r_token.json().get("result", {}).get("token")

            headers = {
                "User-Agent": scraper.headers.get("User-Agent", "Mozilla/5.0"),
                "Accept": "text/plain",
                "X-Api-Key": key,
                "X-Fingerprint-Lite": "e9136c41504646444",
                "Referer": self.hexa_referer,
                "X-Cap-Token": cap_token,
            }

            # 3. Request
            r_enc = scraper.get(url, headers=headers, timeout=10)
            if r_enc.status_code != 200:
                return []
            enc_data = r_enc.text

            # 4. Decrypt
            payload = {"text": enc_data, "key": key}
            r_dec = scraper.post(
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
                            "headers": {"Referer": self.hexa_referer},
                        }
                    )
                return results
        except:
            pass
        return []

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

    def search_mapple(self, tmdb_id, season=None, episode=None):
        """Extraction via Mapple."""
        if not tmdb_id:
            return []

        base_url = self.mapple_api
        headers = {
            "User-Agent": scraper.headers.get("User-Agent", "Mozilla/5.0"),
            "Referer": f"{base_url}/",
        }

        try:
            # 1. Get Token
            media_type = "movie" if season is None else "tv"
            tv_slug = f"{season}-{episode}" if season else ""
            watch_url = f"{base_url}/watch/{media_type}/{tmdb_id}"
            if season:
                watch_url += f"/{tv_slug}"

            r = scraper.get(watch_url, headers=headers, timeout=10)
            token_match = re.search(
                r'window\.__REQUEST_TOKEN__\s*=\s*"([^"]+)"', r.text
            )
            if not token_match:
                return []
            token = token_match.group(1)

            # 2. Extract Streams (Iterate through sources)
            sources = [
                "mapple",
                "sakura",
                "oak",
                "willow",
                "cherry",
                "pines",
                "magnolia",
                "sequoia",
            ]
            results = []

            for source in sources:
                try:
                    payload = {
                        "data": {
                            "mediaId": int(tmdb_id),
                            "mediaType": media_type,
                            "tv_slug": tv_slug,
                            "source": source,
                        },
                        "endpoint": "stream-encrypted",
                    }

                    r_enc = scraper.post(
                        f"{base_url}/api/encrypt",
                        json=payload,
                        headers=headers,
                        timeout=10,
                    )
                    stream_path = r_enc.json().get("url")
                    if not stream_path:
                        continue

                    final_url = f"{base_url}{stream_path}&requestToken={token}"
                    r_streams = scraper.get(
                        final_url, headers=headers, timeout=10
                    ).json()

                    if r_streams.get("success"):
                        stream_url = r_streams.get("data", {}).get("stream_url")
                        if stream_url:
                            results.append(
                                {
                                    "source": f"Mapple ({source.upper()})",
                                    "quality": "1080p",
                                    "url": stream_url,
                                    "type": "M3U8",
                                    "headers": {"Referer": f"{base_url}/"},
                                }
                            )
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
            results.extend(self.search_xpass(tmdb_id, season, episode))

        # Deduplication by URL
        unique = {}
        for r in results:
            if r["url"] and r["url"] not in unique:
                unique[r["url"]] = r
        return list(unique.values())


# Instantiate a global instance for easy use
goldenms_extractor = MediaExtractor()
