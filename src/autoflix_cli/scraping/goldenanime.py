import queue
import threading
import time
import urllib.parse

from curl_cffi import requests as cffi_requests

from .config import portals

scraper = cffi_requests.Session(impersonate="chrome", allow_redirects="safe")

# Providers do not share a payload shape: mkissa answers with ``sources``
# (``extractedUrl``/``extractedType``/``headers``), animegg with ``streams``.
# Reading only one of them silently dropped every mkissa stream.
WATCH_STREAM_KEYS = ("sources", "streams")

# Referers for providers whose payload carries no headers. Used before
# falling back to the URL host so CDN links still get the player referer.
PROVIDER_REFERERS = {
    "mkissa": "https://mkissa.to/",
    "animegg": "https://www.animegg.org/",
}


class AnimeExtractor:
    """
    Original Version (VO) anime extractor based on a stable REST aggregator.

    Uses the Anivexa-style API: metadata, episode lists and stream links are
    resolved from an AniList ID (no DOM scraping). Multiple public instances
    are tried in order, so a dead deployment only requires changing a URL in
    ``data/source_portal.jsonc`` instead of rewriting a scraper.
    """

    # Providers order by stream quality preference (best first).
    # This mirrors the provider list advertised by the API itself: ``allmanga``
    # is gone, while the newer providers are kept as low-priority fallbacks.
    PROVIDER_PRIORITY = [
        "mkissa",
        "animegg",
        "anikoto",
        "aniwaves",
        "anineko",
        "anidbapp",
        "animenosub",
        "animedunya",
        "animeonsen",
        "anipm",
        "senshi",
        "kaa",
        "reanime",
        "anibd",
        "anizone",
        "2dhive",
    ]

    # /episodes aggregates a dozen providers, so a cold id takes 20-35s and a
    # loaded instance can need 80s+. A hung base should not block the others
    # for minutes, but the menu is progressive: waiting longer only adds extra
    # providers to a list the user can already browse.
    EPISODES_TIMEOUT = 45
    # /watch is usually fast, but animegg regularly lands past 20s and MKissa
    # answers 403 after ~27s on the instances that block it. Failures are
    # remembered, so only the first episode of a session pays them.
    WATCH_TIMEOUT = 35
    # Ceiling for the blocking ``extract_vo`` (API clients, tests).
    EXTRACT_TIMEOUT = 60

    def __init__(self):
        self.bases = [
            portals.get("aniwatch", "https://anivexa.otakunaija.name.ng"),
            portals.get(
                "aniwatch-fallback", "https://anivexa-api-navy.vercel.app"
            ),
            portals.get("aniwatch-fallback2", "https://bashapi.tech"),
        ]
        self.referer = portals.get("aniwatch-referer", "https://anizone.to")
        # anilist_id -> {base: payload}. Payloads are kept per base so a fast
        # but incomplete answer (bashapi only lists reanime) does not hide the
        # providers the slower bases know about.
        self._episodes_cache = {}
        self._cache_lock = threading.Lock()
        # (provider, base) pairs that already failed in this session, so a
        # blocked provider is not retried on every episode.
        self._watch_failures = set()

    def _request_json(self, base, path, timeout=20):
        """GET a JSON payload from one base, or ``None`` on any failure."""
        try:
            r = scraper.get(base + path, timeout=timeout)
            if r.status_code == 200:
                return r.json()
        except Exception:
            return None
        return None

    def _get_json(self, path, timeout=20):
        """GET a JSON payload from the first base that answers."""
        for base in self.bases:
            data = self._request_json(base, path, timeout=timeout)
            if data is not None:
                return data
        return None

    def get_mappings(self, anilist_id):
        """Cross-platform IDs (anidbId, imdbId, malId...) for an AniList ID."""
        data = self._get_json(f"/map/{anilist_id}")
        if data and isinstance(data, dict):
            return data.get("mappings") or {}
        return {}

    def _resolve_anilist_id(self, title):
        """Fallback: resolve an AniList ID from a title when it is missing."""
        if not title:
            return None
        try:
            from ..anilist import anilist_client

            results = anilist_client.search_media(title)
            if results:
                return results[0]["id"]
        except Exception:
            pass
        return None

    @staticmethod
    def _has_episodes(data):
        """True when a payload carries at least one provider episode list."""
        return isinstance(data, dict) and any(
            isinstance(v, dict) and isinstance(v.get("episodes"), dict)
            for v in data.values()
        )

    def cached_episodes(self, anilist_id):
        """Cached ``{base: payload}`` for an AniList ID (may be empty)."""
        with self._cache_lock:
            return dict(self._episodes_cache.get(anilist_id) or {})

    def _remember_episodes(self, anilist_id, base, data):
        with self._cache_lock:
            self._episodes_cache.setdefault(anilist_id, {})[base] = data

    @staticmethod
    def _host_referer(url):
        """``https://host/`` for a stream URL, or ``None`` when unparsable."""
        try:
            parsed = urllib.parse.urlsplit(url or "")
        except ValueError:
            return None
        if not parsed.scheme or not parsed.netloc:
            return None
        return f"{parsed.scheme}://{parsed.netloc}/"

    def _subtitles_from_tracks(self, tracks, headers):
        subtitles = []
        for track in tracks or []:
            if not isinstance(track, dict):
                continue
            url = track.get("url")
            if not url:
                continue
            subtitles.append(
                {
                    "lang": track.get("srclang") or track.get("language_code") or "?",
                    "label": track.get("label") or track.get("lang") or "Unknown",
                    "url": url,
                    "format": track.get("format"),
                    "default": bool(track.get("default")),
                    # Subtitle CDNs enforce the same referer as the stream
                    # (often the host player like megaplay.buzz); propagate it.
                    "headers": dict(headers),
                }
            )
        return subtitles or None

    def _stream_headers(self, stream, provider=None, url=None):
        """Playback headers: payload headers, then referer fallbacks."""
        headers = {
            key: value
            for key, value in (stream.get("headers") or {}).items()
            if value
        }
        if not headers.get("Referer"):
            referer = (
                stream.get("referer")
                or PROVIDER_REFERERS.get(provider or "")
                or self._host_referer(url)
                or self.referer + "/"
            )
            headers["Referer"] = referer
        return headers

    @staticmethod
    def _stream_type(stream, url):
        """Map the provider's vocabulary (direct/mp4/iframe) to our types."""
        stype = (stream.get("extractedType") or stream.get("type") or "").lower()
        lowered = url.lower()
        if stype in ("hls", "hls-redirect"):
            return "M3U8"
        if stype in ("mpd", "dash"):
            return "MPD"
        if stype == "mp4":
            return "MP4"
        if stype in ("embed", "iframe", "player"):
            return "Player"
        # ``direct`` (mkissa) is a plain media file, often served from a CDN
        # without an extension: trust it and fall back to the URL suffix.
        if stype == "direct":
            if ".m3u8" in lowered:
                return "M3U8"
            if ".mpd" in lowered:
                return "MPD"
            return "MP4"
        if ".m3u8" in lowered:
            return "M3U8"
        if ".mpd" in lowered:
            return "MPD"
        if ".mp4" in lowered:
            return "MP4"
        return "Player"

    def _stream_entry(self, provider, stream, language, payload_subtitles=None):
        # Providers disagree on field names: mkissa fills extractedUrl/name,
        # animegg only url/type. Normalise both shapes here.
        url = stream.get("extractedUrl") or stream.get("url")
        if not url:
            return None

        out_type = self._stream_type(stream, url)
        server = stream.get("name") or stream.get("server") or provider
        headers = self._stream_headers(stream, provider=provider, url=url)
        tracks = stream.get("subtitles") or payload_subtitles

        return {
            "source": f"Anivexa ({provider} - {server})",
            "quality": "Auto",
            "url": url,
            "type": out_type,
            "headers": headers,
            "subtitles": self._subtitles_from_tracks(tracks, headers),
            "language": language,
        }

    @staticmethod
    def _watch_streams(watch_data):
        """Stream entries from either payload shape (``sources``/``streams``)."""
        for key in WATCH_STREAM_KEYS:
            streams = watch_data.get(key)
            if not isinstance(streams, list):
                continue
            for stream in streams:
                if isinstance(stream, dict):
                    yield stream

    @staticmethod
    def _priority(stream):
        try:
            return float(stream.get("priority") or 0)
        except (TypeError, ValueError):
            return 0.0

    def progressive_search(
        self, anilist_id, episode, lang="sub", deadline_seconds=75
    ):
        """Start resolving one episode in the background.

        The returned :class:`ProgressiveSearch` exposes ``snapshot()`` which
        grows as instances and providers answer, so the caller can show the
        first streams immediately and keep appending the rest.
        """
        return ProgressiveSearch(
            self,
            anilist_id,
            episode,
            lang=lang,
            deadline_seconds=deadline_seconds,
        )

    def extract_vo(self, title=None, anilist_id=None, episode=1, lang="sub"):
        """
        Search, deduplication, and sorting.

        Returns the same structure as before:
        ``{"source", "quality", "url", "type", "headers", "subtitles"}``.
        """
        if not anilist_id and title:
            anilist_id = self._resolve_anilist_id(title)
        if not anilist_id:
            return []

        search = self.progressive_search(anilist_id, episode, lang=lang)
        search.start()
        search.wait(self.EXTRACT_TIMEOUT)
        return search.ranked()


class ProgressiveSearch:
    """Resolve one episode while the caller already consumes the results.

    ``/episodes`` is requested on every base at once: the first valid payload
    unlocks the ``/watch`` calls, and the slower bases still contribute their
    own providers when they finally answer. ``/watch`` runs one worker per
    provider, so a provider blocked on one instance (MKissa answers 500/403
    on most of them) no longer delays the others.

    Workers are daemons and never print: the caller renders ``snapshot()``
    from the main thread, which is what lets the menu grow while playback is
    already running. A global deadline stops the long tail of a slow instance
    (a provider is tried on three bases, each with its own timeout).
    """

    # Grace period before a provider is also asked from the other instances.
    # MKissa answers 403 after 27s on the primary instance while Vercel serves
    # it in 0.2s; most other providers do answer where they were listed, so
    # the extra requests are only sent when the first base is really slow.
    HEDGE_DELAY = 1.5

    def __init__(
        self,
        extractor,
        anilist_id,
        episode,
        lang="sub",
        max_workers=8,
        deadline_seconds=75,
    ):
        self._extractor = extractor
        self.anilist_id = int(anilist_id)
        self.episode = episode
        self.lang = lang
        self._deadline = time.monotonic() + deadline_seconds
        self._semaphore = threading.Semaphore(max_workers)
        self._lock = threading.Lock()
        # (priority, arrival, entry): priority sorts the blocking API, arrival
        # keeps the progressive menu stable from one render to the next.
        self._entries = []
        self._seen_urls = set()
        self._providers = {}
        self._pending = 0
        self._arrival = 0
        self._done = threading.Event()
        # Set on the first stream, or when there is no more work to wait for.
        self._ready = threading.Event()
        self._stop = threading.Event()
        # ``start()`` is still spawning workers: a worker reaching zero must
        # not declare the search finished before the last one is queued.
        self._open = True

    # -- public API ---------------------------------------------------
    def start(self):
        cached = self._extractor.cached_episodes(self.anilist_id)
        for base, data in cached.items():
            self._register(data, base)
        for base in self._extractor.bases:
            if base in cached:
                continue
            self._spawn(self._episodes_worker, base)
        with self._lock:
            self._open = False
            finished = self._pending <= 0
        if finished:
            self._done.set()
            self._ready.set()
        return self

    def stop(self):
        """Ask the workers not to start any new request."""
        self._stop.set()

    def wait(self, timeout=None):
        """Block until every worker is done, or ``timeout`` elapses."""
        return self._done.wait(timeout)

    def wait_for_first(self, timeout):
        """Wait for the first stream, the end of the search, or ``timeout``."""
        self._ready.wait(timeout)
        return bool(self.snapshot())

    def is_done(self):
        return self._done.is_set()

    def pending(self):
        """Number of requests still in flight."""
        with self._lock:
            return self._pending

    def snapshot(self):
        """Streams found so far, in arrival order (stable across renders)."""
        with self._lock:
            return [entry for _, _, entry in self._entries]

    def ranked(self):
        """Streams found so far, best provider-declared priority first."""
        with self._lock:
            rows = sorted(self._entries, key=lambda row: (-row[0], row[1]))
        return [entry for _, _, entry in rows]

    # -- workers ------------------------------------------------------
    def _spawn(self, target, *args):
        with self._lock:
            self._pending += 1
        thread = threading.Thread(target=self._run, args=(target, args), daemon=True)
        thread.start()

    def _run(self, target, args):
        try:
            target(*args)
        except Exception:  # noqa: BLE001 - one broken worker must not stop the rest
            pass
        finally:
            with self._lock:
                self._pending -= 1
                finished = self._pending <= 0 and not self._open
            if finished:
                self._done.set()
                self._ready.set()

    def _get(self, base, path, timeout):
        with self._semaphore:
            if self._stop.is_set() or time.monotonic() >= self._deadline:
                return None
            return self._extractor._request_json(base, path, timeout=timeout)

    def _episodes_worker(self, base):
        data = self._get(
            base,
            f"/episodes/{self.anilist_id}",
            self._extractor.EPISODES_TIMEOUT,
        )
        if not self._extractor._has_episodes(data):
            return
        # Cache per base: a fast but partial answer must not hide the
        # providers the slower instances list.
        self._extractor._remember_episodes(self.anilist_id, base, data)
        self._register(data, base)

    def _register(self, data, base):
        """Spawn a ``/watch`` worker for every provider this payload lists."""
        for provider in self._extractor.PROVIDER_PRIORITY:
            if self._stop.is_set() or time.monotonic() >= self._deadline:
                return
            node = data.get(provider)
            if not isinstance(node, dict):
                continue
            episodes = node.get("episodes")
            if not isinstance(episodes, dict):
                continue
            episode_list = episodes.get(self.lang) or episodes.get("sub") or []
            target = next(
                (ep for ep in episode_list if ep.get("number") == self.episode),
                None,
            )
            ep_id = target.get("id") if target else None
            if not ep_id:
                continue
            with self._lock:
                if provider in self._providers:
                    continue  # the fastest base already owns this provider
                self._providers[provider] = base
            self._spawn(self._watch_worker, provider, ep_id, base)

    def _watch_worker(self, provider, ep_id, listed_by):
        """First base that really returns streams for this provider.

        The base that listed the episodes is asked first. If it does not
        answer within ``HEDGE_DELAY`` (or fails), the other instances are
        asked in parallel and the first real answer wins: MKissa is served by
        Vercel in 0.2s while the primary instance takes 27s to answer 403.
        Failed pairs are remembered for the session so the next episode goes
        straight to the base that works.
        """
        path = "/" + ep_id.lstrip("/")
        ordered = [listed_by] + [
            base for base in self._extractor.bases if base != listed_by
        ]
        candidates = [
            base
            for base in ordered
            if (provider, base) not in self._extractor._watch_failures
        ]
        if not candidates:
            return

        results = queue.Queue()
        in_flight = 0
        hedged = False

        def probe(base):
            payload = self._get(base, path, self._extractor.WATCH_TIMEOUT)
            results.put((base, payload))

        def start(base):
            nonlocal in_flight
            threading.Thread(target=probe, args=(base,), daemon=True).start()
            in_flight += 1

        start(candidates.pop(0))
        while in_flight:
            timeout = None
            if not hedged and candidates:
                timeout = self.HEDGE_DELAY
            try:
                base, payload = results.get(timeout=timeout)
            except queue.Empty:
                # Slow base: ask the others without waiting for its timeout.
                hedged = True
                while candidates:
                    start(candidates.pop(0))
                continue

            in_flight -= 1
            if payload and any(True for _ in self._extractor._watch_streams(payload)):
                self._collect(provider, payload)
                return
            self._extractor._watch_failures.add((provider, base))
            if candidates and not hedged:
                # Failed fast: no reason to wait for the grace period.
                hedged = True
                while candidates:
                    start(candidates.pop(0))

    def _collect(self, provider, data):
        payload_subtitles = data.get("subtitles")
        for stream in self._extractor._watch_streams(data):
            entry = self._extractor._stream_entry(
                provider, stream, self.lang, payload_subtitles
            )
            if not entry:
                continue
            url = entry.get("url")
            priority = self._extractor._priority(stream)
            with self._lock:
                if not url or url in self._seen_urls:
                    continue
                self._seen_urls.add(url)
                self._entries.append((priority, self._arrival, entry))
                self._arrival += 1
                self._ready.set()


# Instantiate a global instance for easy use
goldenanime = AnimeExtractor()
