"""Public Python API for AutoFlix-CLI.

A thin, provider-agnostic facade over the scrapers, extractors and player
proxy. Everything lives behind a handful of generic functions:

    search()     -> find content across the text-search providers
    get()        -> resolve a URL into a normalized Content/Episode object
    extract()    -> resolve an embed player URL into a direct stream URL
    anime()      -> stream entries for an anime, by AniList ID or title
    media()      -> stream entries for a movie/series, by TMDB ID
    start_proxy() / proxy_url() / stop_proxy() -> local playback proxy

Typical flow::

    import autoflix_cli.api as af

    for r in af.search("one piece"):
        print(r.provider, r.title, r.url)

    content = af.content(r)            # movie or series, one normalized shape
    if content.kind == "movie":
        stream = af.extract(content.players[0])
"""

from urllib.parse import quote
import json

from .scraping.player import get_hls_link as _get_hls_link
from .scraping.player import is_supported as _is_supported
from .scraping import anime_sama, arkanime, coflix, french_stream
from .scraping.goldenanime import goldenanime
from .scraping.goldenms import goldenms_extractor
from . import proxy as _proxy

__all__ = [
    "Content",
    "Episode",
    "Player",
    "PROVIDERS",
    "Result",
    "Season",
    "anime",
    "extract",
    "get",
    "media",
    "proxy_url",
    "search",
    "start_proxy",
    "stop_proxy",
    "to_dict",
]


# ---------------------------------------------------------------------------
# Normalized data model
# ---------------------------------------------------------------------------
# Every provider returns its own object types (CoflixSeries, SamaSeason,
# ArkMovie...). The API converts them into the single model below so callers
# never have to know the provider internals.


class Result:
    """A search result, tagged with the provider that produced it."""

    def __init__(self, provider: str, title: str, url: str, img: str = None, genres: list[str] = None):
        self.provider = provider
        self.title = title
        self.url = url
        self.img = img
        self.genres = genres or []

    def __str__(self):
        return f"Result(provider='{self.provider}', title='{self.title}', url='{self.url}')"

    def __repr__(self):
        return str(self)


class Player:
    """An embed player attached to a movie or episode (its URL can be fed to extract())."""

    def __init__(self, name: str, url: str, provider: str = None):
        self.provider = provider
        self.name = name
        self.url = url

    def __str__(self):
        return f"Player(provider='{self.provider}', name='{self.name}', url='{self.url}')"

    def __repr__(self):
        return str(self)


class Episode:
    """An episode.

    ``players`` is set when they are already known, otherwise the episode only
    carries its ``url``: call :func:`get` on that URL to load the players.
    """

    def __init__(self, title: str, url: str = None, players: list[Player] = None, provider: str = None):
        self.provider = provider
        self.title = title
        self.url = url
        self.players = players

    def __str__(self):
        return f"Episode(provider='{self.provider}', title='{self.title}', url='{self.url}', players={self.players})"

    def __repr__(self):
        return str(self)


class Season:
    """A season of episodes (``episodes`` may be lazy: fetch it via :func:`get`)."""

    def __init__(self, title: str, url: str = None, episodes: list[Episode] = None, provider: str = None):
        self.provider = provider
        self.title = title
        self.url = url
        self.episodes = episodes

    def __str__(self):
        return f"Season(provider='{self.provider}', title='{self.title}', url='{self.url}')"

    def __repr__(self):
        return str(self)


class Content:
    """A piece of content in one normalized shape.

    ``kind`` is ``"movie"``, ``"series"`` or ``"season"``:

    * movie:   ``players`` is set (embed players, feed them to :func:`extract`)
    * series:  ``seasons`` is set (mostly lazy - one entry per real season)
    * season:  ``seasons`` is set and fully loaded - one entry per *language*
               (e.g. anime-sama vostfr/vf, french-stream vo/vostfr/vf). Use
               ``content.seasons[0].episodes`` to reach the episodes.
    """

    def __init__(
        self,
        provider: str,
        kind: str,
        title: str,
        url: str,
        img: str = None,
        genres: list[str] = None,
        players: list[Player] = None,
        seasons: list[Season] = None,
        episodes: list[Episode] = None,
    ):
        self.provider = provider
        self.kind = kind
        self.title = title
        self.url = url
        self.img = img
        self.genres = genres or []
        self.players = players
        self.seasons = seasons
        self.episodes = episodes

    def __str__(self):
        return f"Content(provider='{self.provider}', kind='{self.kind}', title='{self.title}', url='{self.url}')"

    def __repr__(self):
        return str(self)


# ---------------------------------------------------------------------------
# Provider registry
# ---------------------------------------------------------------------------

PROVIDERS = {
    "coflix": "Movies and series (VF/VOSTFR)",
    "anime-sama": "Anime catalogue (VOSTFR, VF and more, seasons playable per language)",
    "french-stream": "French catalogue (movies and series)",
    "arkanime": "Anime (Arkanime API)",
}

# Providers the search() merged mode runs on (i.e. all of them).
_TEXT_PROVIDERS = list(PROVIDERS.keys())

# Anime-Sama language codes used to detect a season URL
# (a season page ends with the language, e.g. .../saison1/vostfr).
_SAMA_LANG_CODES = {"vostfr", "vf", "vj", "vcn", "vqc", "vkr", "va", "vf1", "vf2"}


def _norm_provider(provider) -> str:
    """Normalize or validate a provider name (case, underscore/space/hyphen)."""
    name = str(provider).strip().lower().replace("_", "-").replace(" ", "-")
    if name not in PROVIDERS:
        raise ValueError(f"Unknown provider {provider!r}. Valid: {', '.join(_TEXT_PROVIDERS)}")
    return name


def _infer_provider(url: str):
    """Guess the provider from a URL. None when it is not recognizable."""
    u = str(url).lower()
    if "coflix" in u:
        return "coflix"
    if "anime-sama" in u or "/catalogue/" in u:
        return "anime-sama"
    if "french-stream" in u:
        return "french-stream"
    if "arkanime" in u:
        return "arkanime"
    return None


def _ready(provider: str):
    """Lazy per-provider initialization (base URL discovery where needed)."""
    if provider == "coflix":
        coflix.get_website_url()
    elif provider == "anime-sama":
        anime_sama.get_website_url()
    elif provider == "arkanime":
        arkanime.get_website_url()
    # french-stream has its origin at import time


# ---------------------------------------------------------------------------
# search / get
# ---------------------------------------------------------------------------


def search(query: str, provider: str = None) -> list[Result]:
    """Search content on one provider or across all of them.

    Args:
        query: Text to look up (title, keywords...).
        provider: Optional provider name (``"coflix"``, ``"anime-sama"``,
            ``"french-stream"``, ``"arkanime"``). ``None`` searches them all
            and merges the results (each tagged with ``.provider``).

    Returns:
        List of :class:`Result`. If every provider fails an exception is
        raised; individual failures are skipped in merged mode.
    """
    providers = [_norm_provider(provider)] if provider else _TEXT_PROVIDERS

    results: list[Result] = []
    last_error = None
    for p in providers:
        try:
            _ready(p)
            module = {
                "coflix": coflix,
                "anime-sama": anime_sama,
                "french-stream": french_stream,
                "arkanime": arkanime,
            }[p]
            for r in module.search(query):
                results.append(Result(p, r.title, r.url, r.img, r.genres))
        except Exception as e:
            last_error = e
            if provider:  # single provider: fail loudly
                raise

    if not results and last_error is not None:
        raise RuntimeError(f"All providers failed, last error: {last_error}") from last_error
    return results


def get(provider=None, url: str = None):
    """Resolve a provider URL into a normalized object.

    This is the generic navigation primitive: what comes back depends on the
    URL itself (movie, series, season or episode page). Call it repeatedly to
    walk down until you reach players you can feed to :func:`extract`.

    Args:
        provider: Provider name, optionally omitted when ``url`` is a full
            URL that speaks for itself (coflix, anime-sama, french-stream,
            arkanime) — ``af.get(url_string)`` alone is accepted too. Or a
            :class:`Result` (then ``url`` is ignored), or an
            :class:`Episode`/``Season`` with a ``url`` but no players.
        url: Content URL on that provider.

    Returns:
        * :class:`Content` for any other URL. ``kind`` says which shape:
          ``"movie"`` (``.players`` set), ``"series"`` (``.seasons``, mostly
          lazy) or ``"season"`` (``.seasons``, one per language, episodes
          fully loaded with players).
        * :class:`Episode` when the URL is an episode page (players loaded).

    Raises:
        NoEpisodesFoundError: anime-sama content that has no released links yet.
        Exception: whatever the underlying provider raises (network, scrape).
    """

    def with_url(obj, url):
        obj.url = url
        return obj

    # Single-argument style: the URL as the only positional parameter.
    if url is None and isinstance(provider, str):
        provider, url = None, provider

    # Accept any API object that carries its own navigation URL.
    if isinstance(provider, (Result, Episode, Season, Content)) and url is None:
        provider, url = provider.provider, provider.url

    if url is None:
        raise ValueError(
            "Nothing to resolve: pass (provider, url), or any API object carrying "
            "a navigation URL (Result, lazy Season/Episode). For lazy Season "
            "entries without a URL (coflix), navigate with af.get(episode) instead."
        )

    # Full URL without provider name: infer it from the URL itself.
    if provider is None:
        provider = _infer_provider(url)
        if provider is None:
            raise ValueError(
                "Could not determine the provider from this URL: pass "
                f"provider= explicitly ({', '.join(_TEXT_PROVIDERS)})."
            )

    name = _norm_provider(provider)
    _ready(name)

    if name == "coflix":
        if "/episode/" in url:
            ep = coflix.get_episode(url)
            players = [Player(p.name, p.url, name) for p in ep.players]
            return Episode(ep.title, url, players, name)
        c = coflix.get_content(url)
        if isinstance(c, coflix.CoflixMovie):
            players = [Player(p.name, p.url, name) for p in c.players]
            return Content(name, "movie", c.title, url, c.img, c.genres, players=players)
        seasons = [
            Season(s.title, None, [Episode(e.title, e.url, None, name) for e in s.episodes], name)
            for s in c.seasons
        ]
        return Content(name, "series", c.title, url, c.img, c.genres, seasons=seasons)

    if name == "anime-sama":
        if url.rstrip("/").rsplit("/", 1)[-1] in _SAMA_LANG_CODES:
            return _sama_season(url, name)
        s = anime_sama.get_series(url)
        seasons = [Season(sa.title, sa.url, None, name) for sa in s.seasons]
        return Content(name, "series", s.title, url, s.img, s.genres, seasons=seasons)

    if name == "french-stream":
        c = french_stream.get_content(url)
        if isinstance(c, french_stream.FrenchStreamMovie):
            players = [Player(p.name, p.url, name) for p in c.players]
            return Content(name, "movie", c.title, url, c.img, c.genres, players=players)
        # FrenchStreamSeason: episodes keyed by language.
        seasons = [
            Season(
                lang,
                c.url,
                [Episode(f"{ep.title}", None, [Player(p.name, p.url, name) for p in ep.players], name) for ep in eps],
                name,
            )
            for lang, eps in c.episodes.items()
        ]
        return Content(name, "season", c.title, url, None, [], seasons=seasons)

    # arkanime
    c = arkanime.get_content(url)
    if isinstance(c, arkanime.ArkMovie):
        players = [Player(p.name, p.url, name) for p in c.players]
        return Content(name, "movie", c.title, c.id, c.img, c.genres, players=players)
    seasons = [
        Season(s.title, s.id, [Episode(e.title, None, [Player(p.name, p.url, name) for p in e.players], name) for e in s.episodes], name)
        for s in c.seasons
    ]
    return Content(name, "series", c.title, c.id, c.img, c.genres, seasons=seasons)


def _sama_season(url: str, name: str):
    """Load an Anime-Sama season page and merge its languages."""
    season = anime_sama.get_season(url)
    multi = len(season.lang) > 1
    seasons = [
        Season(
            lang if multi else season.title,
            url,
            [Episode(e.title, None, [Player(p.name, p.url, name) for p in e.players], name) for e in eps],
            name,
        )
        for lang, eps in season.episodes.items() if eps
    ]
    return Content(name, "season", season.title, url, None, [], seasons=seasons)


# ---------------------------------------------------------------------------
# Stream extraction
# ---------------------------------------------------------------------------


def extract(url, headers: dict = None, provider: str = None, return_subs: bool = False):
    """Resolve an embed player URL into a direct stream URL.

    Args:
        url: Embed player URL. A :class:`Player` from the model above is
            accepted too (its ``provider`` is used automatically).
        headers: HTTP headers for the request. When omitted, sensible
            defaults are derived from ``provider`` (e.g. the site Referer);
            when ``provider`` is None it is inferred from the URL when
            possible.
        provider: Provider name the URL came from (also inferred from a
            :class:`Player` argument, or from a shorthand URL like
            ``montmyoboky:1234`` which belongs to Arkanime).
        return_subs: Also return the extracted subtitle URL
            ``(stream_url, subtitle_url)``.

    Returns:
        Stream URL (HLS ``.m3u8`` or video file), or ``None`` when nothing
        could be extracted. With ``return_subs``, a ``(stream, subs)`` tuple.
    """
    if isinstance(url, Player):
        provider, url = url.provider, url.url

    name = _norm_provider(provider) if provider else None

    # Shorthand embeds (e.g. "montmyoboky:9646") are Arkanime: the stream
    # lives behind the provider API, whose origin must be initialized.
    if not name:
        u = str(url).lower()
        if u.startswith("montmyoboky"):
            name = "arkanime"
        else:
            name = _infer_provider(u)

    headers = dict(headers or {})
    if name == "coflix":
        coflix.get_website_url()
        headers.setdefault("Referer", coflix.website_origin)
    elif name == "arkanime":
        arkanime.get_website_url()
        headers.setdefault("Referer", arkanime.website_origin)

    return _get_hls_link(url, headers, return_subs)


def is_supported(url: str) -> bool:
    """Check whether an embed player URL is supported by the extractors."""
    return _is_supported(url)


# ---------------------------------------------------------------------------
# ID-based sources (no search needed, an external ID is the input)
# ---------------------------------------------------------------------------


def anime(anilist_id: int = None, title: str = None, episode: int = 1, lang: str = "sub") -> list[dict]:
    """Stream entries for one episode of an anime, by AniList ID (or title).

    Args:
        anilist_id: AniList ID of the anime. If omitted it is resolved from
            ``title`` through AniList.
        title: Anime title, used when ``anilist_id`` is None.
        episode: Episode number.
        lang: ``"sub"`` (VOSTFR, default) or ``"dub"``.

    Returns:
        List of stream entries: dicts with ``source``, ``quality``, ``url``,
        ``type``, ``headers``, ``subtitles``. ``type`` is ``"M3U8"``/``"MP4"``
        for direct streams (playable or proxied as is) or ``"Player"`` for
        embed pages (feed those to :func:`extract`).
    """
    return goldenanime.extract_vo(title=title, anilist_id=anilist_id, episode=episode, lang=lang)


def media(tmdb_id: int = None, season: int = None, episode: int = None, title: str = None, year: int = None, imdb_id: str = None) -> list[dict]:
    """Stream entries for a movie or an episode of a series, by TMDB ID.

    Args:
        tmdb_id: TMDB ID. Movies omit ``season``/``episode``; series pass both.
        season / episode: For series.
        title, year, imdb_id: Optional hints improving the hit rate of some
            upstream sources.

    Returns:
        Same shape as :func:`anime`: list of stream-entry dicts.
    """
    return goldenms_extractor.extract(
        title=title, tmdb_id=tmdb_id, imdb_id=imdb_id, year=year, season=season, episode=episode
    )


# ---------------------------------------------------------------------------
# Playback proxy
# ---------------------------------------------------------------------------


def start_proxy(port: int = 0) -> str:
    """Start the local playback proxy ( HLS rewriting + segment fetching).

    Args:
        port: Port to listen on. 0 (default) picks a free one.

    Returns:
        Base URL of the proxy, e.g. ``"http://127.0.0.1:48913"``.
    """
    _proxy.start_proxy_server(port)
    return _proxy.PROXY_URL


def stop_proxy():
    """Shut the local proxy down."""
    _proxy.stop_proxy_server()


def proxy_url(stream_url: str, headers: dict = None, kind: str = "stream") -> str:
    """Rewrite a direct stream URL into a local, player-friendly proxy URL.

    Handy for players that cannot pass HTTP headers (mpv, VLC...) or when
    the source needs HLS playlist rewriting.

    Args:
        stream_url: Direct stream URL (``.m3u8`` or video file).
        headers: Headers the upstream expects (Referer, User-Agent...).
        kind: ``"stream"`` for HLS playlists (default), ``"video"`` for a
            plain progressive video file.

    Returns:
        URL on the local proxy. The proxy must be started first
        (:func:`start_proxy`), otherwise a ``RuntimeError`` is raised.
    """
    if not _proxy.PROXY_PORT:
        raise RuntimeError("Proxy is not running: call start_proxy() first.")
    endpoint = "video" if kind == "video" else "stream"
    h = json.dumps(headers or {})
    return f"{_proxy.PROXY_URL}/{endpoint}?url={quote(stream_url)}&headers={quote(h)}"


# ---------------------------------------------------------------------------
# Serialization helper
# ---------------------------------------------------------------------------


def to_dict(value):
    """Convert any API object (or list/nested structure of them) into plain dict/list data."""
    if hasattr(value, "__dict__"):
        return {k: to_dict(v) for k, v in value.__dict__.items() if not k.startswith("_") and not callable(v)}
    if isinstance(value, list):
        return [to_dict(v) for v in value]
    return value
