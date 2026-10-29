# AutoFlix — CLI Flags Guide

`autoflix` works in two modes:

- **No flags** → the classic interactive menus (as always).
- **With flags** → one-shot, non-interactive commands: search, inspect
  content and resolve streams straight from your shell. Ideal for scripts
  and pipes.

## Commands

| Flag                    | Action                                            |
| ------------------------| ------------------------------------------------- |
| `--search QUERY`        | Search content on the providers                    |
| `--url URL`             | Show content details for a provider URL            |
| `--index N` (with search)| Show the details of result `N` instead of the list |
| `--extract PLAYER_URL`  | Resolve an embed player URL into a direct stream   |
| `--force`               | With `--extract`: brute-force every extractor and print a full report |
| `--providers`           | List the available providers                       |

> Player URLs: the `https://...` links listed in the **players** of a
> movie/episode, or **episode URLs** listing a season detail (e.g. a coflix
> `https://.../episode/...` link). See the examples.

## Options

| Flag               | Action                                                  |
| -------------------| --------------------------------------------------------|
| `--provider NAME`  | Restrict to one provider: `coflix`, `anime-sama`, `french-stream`, `arkanime`. **Optional** — for `--url`/`--extract` it is detected from the URL itself. |
| `--json`           | Machine-readable JSON output instead of a pretty table   |
| `--version`        | Print the version                                        |

## Examples

### Search the providers

```bash
autoflix --search "mercredi"                    # all providers
autoflix --search "mercredi" --provider coflix  # one provider
autoflix --search "bofuri" --json               # machine-readable
```

### Inspect content from a search

Show the details of result `#0`:

```bash
autoflix --search "mercredi" --index 0
# Weekly "Wednesday" (coflix, series)
#    seasons:
#      ...
```

Or provide a direct URL (any movie/series/season/episode page):

```bash
autoflix --url "https://coflix.ac/serie/mercredi/" --provider coflix
autoflix --url "https://anime-sama.to/catalogue/bofuri/saison1/vostfr" \
         --provider anime-sama
```

The output lists seasons, episode URLs, and directly playable streams
when there are any.

### Resolve a direct stream

```bash
autoflix --extract "https://sendvid.com/embed/kexnx9jq"
# https://videos2.sendvid.com/.../kexnx9jq.mp4?validfrom=...
```

`--extract` accepts an embed/player URL (like the ones printed by
`--url`/`--index`). For coflix, episode URLs containing a resolved player's
page need an explicit `--provider`:

```bash
autoflix --url "https://coflix.ac/episode/mercredi-1x1/"
         --provider coflix        # print the episode's players
autoflix --extract "https://vidmoly.to/..." --provider coflix
```

The returned URL can be passed to your player:

```bash
mpv "$(autoflix --extract 'https://sendvid.com/embed/xyz')"
```

### When extraction fails: `--force`

The matched extractor does not always manage to resolve a stream
(domains rotate, config drifts). `--force` then runs **every** extractor
against the URL (dev-style brute force) and prints a report with timings:

```bash
autoflix --extract "https://derricknationtop.com/e/c4gbyeojdqdo" --force
# ┌ Extractor report ────────────────────────────────────────────────────┐
# │ voe           yes  0.6s  https://.../master.m3u8?t=...               │
# │ default       no   0.8s  no stream found                            │
# │ ...                                                                  │
# └──────────────────────────────────────────────────────────────────────┘
# https://.../master.m3u8?t=...
```

Every working stream URL is printed below the table; add `--json` for the
raw report. In Python the same report is available as
`af.test_extractors(url)`.

### List the providers

```bash
autoflix --providers
#  coflix         Movies and series (VF/VOSTFR)
#  anime-sama     Anime catalogue (VOSTFR, VF and more, seasons playable per language)
#  french-stream  French catalogue (movies and series)
#  arkanime       Anime (Arkanime API)
```

## Using with pipes

All commands support `--json` so you can consume output with `jq`:

```bash
autoflix --search "bofuri" --json | jq -r '.[].url'
autoflix --search "bofuri" --provider anime-sama --json \
  | jq -r '.[0].url' | xargs -I{} autoflix --url {} --provider anime-sama
```

## Exit codes

| Code | Meaning                                        |
| -----| -----------------------------------------------|
| `0`  | success                                         |
| `1`  | runtime error (network/scrape/unknown stream)   |
| `2`  | bad arguments (argparse)                        |

## Notes

- Search across providers skips providers failing individually (flaky or
  down); the CLI only fails when nothing at all could be found.
- These operations are read-only: nothing is written to your history or
  playing data; the interactive mode remains the way to watch/resume.
