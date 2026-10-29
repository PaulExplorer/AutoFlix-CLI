# AutoFlix — Python API Guide

This guide explains how to use **AutoFlix as a Python library**: the
`autoflix_cli.api` module gives you programmatic access to the content
providers (scrapers), stream extractors and the playback proxy, without
any CLI interaction.

## Installation

```bash
pip install autoflix-cli
# or from source:
git clone https://github.com/PaulExplorer/AutoFlix-CLI
cd AutoFlix-CLI && pip install .
```

## Import

```python
import autoflix_cli.api as af
```

## Concepts

- **Providers** are the content sources. The text-searchable ones are listed
  in `af.PROVIDERS`:

  | Provider        | Content                                      |
  | --------------- | -------------------------------------------- |
  | `coflix`        | Movies and series (VF/VOSTFR)                |
  | `anime-sama`    | Anime catalogue (VOSTFR, VF, VJ...)          |
  | `french-stream` | French catalogue (movies and series)         |
  | `arkanime`      | Anime (Arkanime API)                         |

- **Normalized data model** — every provider returns its own object types
  behind the scenes, but the API always exposes the same four classes:

  - `Result` — a search hit (`.provider`, `.title`, `.url`, `.img`, `.genres`)
  - `Content` — a movie (`kind="movie"`, `.players` set) or a series
    (`kind="series"`, `.seasons` set), or a season page
    (`kind="season"`, `.seasons` — one entry per language — episodes loaded)
  - `Season` — episodes; they may need a lazy fetch
  - `Episode` — players; they may need a lazy fetch (call `af.get()` again)
  - `Player` — an embed player; feed its `.url` to `af.extract()` to get the
    direct stream

- **Stream resolution** — an embed player URL is not playable directly:
  `af.extract()` turns it into a direct `https://.../...m3u8` (or video file)
  URL.

- **Playback proxy** — players such as mpv or VLC cannot pass the HTTP
  headers (Referer...) that many sources require, and some HLS playlists
  need rewriting. `af.start_proxy()` starts a small local server;
  `af.proxy_url()` wraps a stream URL into a playable local one.

## Quick start: search → content → stream

```python
import autoflix_cli.api as af

# 1. Search all providers (or one: af.search("bofuri", provider="anime-sama"))
hits = af.search("bofuri", provider="anime-sama")
hit = hits[0]
print(hit.provider, hit.title, hit.url)

# 2. Load the content
content = af.get(hit)                 # Content(kind="series")
print(content.title, content.seasons)

# 3. Walk down to the players
season = af.get(content.seasons[0])   # Content(kind="season"), episodes loaded
episode = season.seasons[0].episodes[0]   # one entry per language
print(episode.players)

# 4. Resolve a direct stream
stream = af.extract(episode.players[0])
print(stream)                         # https://... .m3u8 or video file
```

## Reference

### `af.search(query, provider=None) -> list[Result]`

Search content on one provider, or on all providers at once (results are
merged and each tagged with its `provider`).

```python
af.search("mercredi")                     # everywhere
af.search("mercredi", provider="coflix")  # one provider
```

If every provider fails, an exception is raised; individual failures are
skipped in merged mode. An unknown provider name raises `ValueError`.

### `af.get(provider, url) -> Content | Episode`

The navigation primitive: resolves a provider URL into a normalized object,
depending on what the URL actually points to.

- `kind="movie"` content: `.players` is a list of `Player`.
- `kind="series"` content: `.seasons`. Two lazy flavors, depending on the
  provider: anime-sama seasons hold a `.url` to fetch (`af.get(season)`),
  while coflix seasons are fetched already but their *episodes* are lazy
  (`af.get(episode)`). Repeat `af.get()` on whichever lazy object you have
  until you reach players.
- `kind="season"` content: `.seasons` — one `Season` per *language*
  (anime-sama VOSTFR/VF, french-stream VO/VOSTFR/VF), episodes fully loaded
  with their players.
- An episode page URL (e.g. a coflix `/episode/...` URL) returns an
  `Episode` with its players.

You can pass whole objects instead of names/URLs — `af.get(result)`,
`af.get(season)` — whenever the object carries its own URL. Enum values are
normalized (`"Anime_Sama"`, `"anime-sama"`... are equivalent).

**Example — coflix movie:**

```python
content = af.get("coflix", "https://coflix.example/film/mercredi-maison/")
for player in content.players:
    print(player.name, player.url)
```

**Example — coflix series (episodes are lazy):**

```python
content = af.get("coflix", "https://coflix.example/serie/gothic/")
season = content.seasons[0]

loaded = af.get(season.episodes[0])    # Episode with .players loaded
stream = af.extract(loaded.players[0])
```

**Example — Arkanime (a single call gives the whole catalog entry):**

```python
content = af.get("arkanime", "313")
for season in content.seasons:
    for episode in season.episodes:
        print(episode.title, episode.players)
```

### `af.extract(url, headers=None, provider=None, return_subs=False)`

Resolve an embed player URL into a direct stream.

```python
stream = af.extract(player)                       # Player object
stream = af.extract("https://sendvid.com/embed/kexnx9jq")
stream, subs = af.extract(embed_url, provider="coflix", return_subs=True)
```

- `headers` — HTTP headers for the request. When omitted, sensible defaults
  are derived from `provider` (e.g. the site `Referer`); coflix and arkanime
  URLs are auto-initialized that way.
- `provider` — where the embed URL came from (also inferred from a `Player`
  argument, or from Arkanime shorthand URLs like `montmyoboky:1234`).
- `return_subs` — also return the subtitle URL: `(stream_url, subtitle_url)`.

Returns the stream URL (`str`), or `None` when nothing could be extracted.

### `af.anime(anilist_id=None, title=None, episode=1, lang="sub") -> list[dict]`

Stream entries for an anime episode, by **AniList ID** (or title — the ID is
then resolved via AniList):

```python
for s in af.anime(anilist_id=1234, episode=1):
    print(s["source"], s["type"], s["url"])
```

`lang` is `"sub"` (VOSTFR, default) or `"dub"`.

### `af.media(tmdb_id=None, season=None, episode=None, title=None, year=None, imdb_id=None) -> list[dict]`

Stream entries for a movie or an episode of a series, by **TMDB ID**:

```python
af.media(tmdb_id=678)                       # movie
af.media(tmdb_id=678, season=1, episode=2)  # series episode
```

Both functions return entries shaped like: `{"source", "quality", "url",
"type", "headers", "subtitles", "language"}`.

- `type="M3U8"` / `"MP4"` — direct stream: playable as is (or proxied).
- `type="Player"` — embed page: pass the `url` to `af.extract()`.

### `af.start_proxy(port=0) -> str`, `af.stop_proxy()`

Start/stop the local playback proxy (HLS rewriting + headerful fetching in
one local server). `start_proxy()` returns the proxy base URL.

### `af.proxy_url(stream_url, headers=None, kind="stream")`

Wrap a direct stream URL into a local URL that any player (mpv, VLC, browser)
can open, no manual headers required:

```python
af.start_proxy()
stream = af.extract(episode.players[0])
url = af.proxy_url(stream, headers={"Referer": "https://player.example"})
print(url)   # http://127.0.0.1:48913/stream?url=...&headers=...
# play it:  mpv <url>
```

- `headers` — headers the **upstream source** expects (Referer,
  User-Agent...). Use the `raw` `stream_entry["headers"]` you got from
  `af.anime()` / `af.media()`.
- `kind` — `"stream"` for HLS playlists (default), `"video"` for a progressive
  video file (`.mp4`, seeking support is preserved).

Raises `RuntimeError` if the proxy is not running.

### `af.to_dict(obj)` / `af.is_supported(url)`

`to_dict` converts any API object (and nested lists of them) into plain
dict/list data — handy to `json.dumps(...)` the workflow output.
`is_supported(url)` simply checks whether an embed URL is known to the
extractors.

## End-to-end examples

### Watch an episode of an anime (with proxy, like the CLI does)

```python
import subprocess
import autoflix_cli.api as af

content = af.get("anime-sama", af.search("bofuri", provider="anime-sama")[0].url)
season = af.get(content.seasons[0])
episode = season.seasons[0].episodes[0]

stream = af.extract(episode.players[0])
af.start_proxy()
subprocess.run(["mpv", af.proxy_url(stream)])
af.stop_proxy()
```

### Movie by TMDB ID (no search involved)

```python
import autoflix_cli.api as af

entries = af.media(tmdb_id=678)
first = entries[0]

if first["type"] == "Player":
    stream = af.extract(first["url"], provider=None)
else:
    stream = first["url"]

af.start_proxy()
print(af.proxy_url(stream, headers=first["headers"], kind="video"))
```

## Limitations

- Network operations are the same the CLI does: the upstream sites can
  change, go down, or require proxies; expect occasional exceptions.
- Some providers (coflix) use anti-bot protection that is resolved
  automatically, but adds latency on first calls.
- Handlers (menus, progress tracking, playback orchestration of the CLI)
  are outside of the scope of this API.

## Development

The implementation lives in `src/autoflix_cli/api.py`, a thin facade over
`autoflix_cli.scraping` (scrapers and extractors) and `autoflix_cli.proxy`
(the playback proxy). Run the CLI suite with `pytest tests/ -q` after any
change. Licensing (GPL-3.0) applies to any reuse of these modules - see
`LICENSE` and `README.md` for the CLI-side documentation.
