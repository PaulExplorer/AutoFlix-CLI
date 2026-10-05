import json
import os
import time
from urllib.parse import urlparse

from ..cli_utils import (
    confirm,
    get_user_input,
    pause,
    print_divider,
    print_error,
    print_header,
    print_info,
    print_success,
    print_warning,
)
from ..scraping.player import PLAYER_EXTRACTORS, test_all_scrapers_verbose
from ..scraping import arkanime
from .. import player_manager as pm


def handle_dev_scraper_test() -> None:
    """Prompt for an embed URL and test every scraper with timings."""
    url = get_user_input("Paste embed URL to test")
    if not url:
        return

    print_info(f"Testing {len(PLAYER_EXTRACTORS)} scrapers...")
    results = test_all_scrapers_verbose(url, {})

    for name, res in results.items():
        elapsed = res["elapsed"]
        if res["ok"]:
            print_success(f"{name} [{elapsed:.1f}s] -> {res['stream_url']}")
        else:
            print_error(f"{name} [{elapsed:.1f}s] failed: {res['error']}")

    working = [n for n, r in results.items() if r["ok"]]
    if working:
        print_success(f"{len(working)} working scraper(s): {', '.join(working)}")
    else:
        print_info("No scraper extracted a stream from this URL.")
    pause()


def _ask_headers() -> dict:
    """Ask for the embed page headers as a JSON object (all optional).

    Most headers are computed from the embed config, but some providers
    (Coflix being one) require their own Referer to be forwarded as is.
    """
    raw = get_user_input(
        'Headers as JSON, e.g. {"Referer": "https://coflix.domains"} (empty = none)'
    )
    if not raw:
        return {}

    import json

    try:
        headers = json.loads(raw)
    except ValueError as e:
        print_error(f"Invalid JSON headers: {e}")
        return {}

    if not isinstance(headers, dict):
        print_error("Headers must be a JSON object.")
        return {}
    return headers


def _launch_candidates(player_config: dict) -> list:
    """Build the (player, mode) combinations available for this embed."""
    candidates = []
    for player_code, modes in pm.PLAYER_MODES.items():
        for mode in modes:
            candidates.append((player_code, mode))

    # Put the combination the config currently resolves to first.
    current = pm.resolve_launch_mode(player_config, "mpv")
    candidates.sort(key=lambda c: 0 if c[1] == current else 1)
    return candidates


def handle_dev_playback_mode_test() -> None:
    """Try every player/mode combination on an embed and report what works."""
    url = get_user_input("Paste embed URL to test")
    if not url:
        return

    player_config, matched = pm._match_player_config(url)

    print_divider()
    if matched:
        print_info(f"Matched embed config: [cyan]{matched}[/cyan]")
    else:
        print_warning("No embed config matched this URL (defaults will be used).")
    print_info(f"Config: {player_config}")
    print_divider()

    # Some extractors (montmyoboky) resolve streams through a provider API
    # whose origin is only set once that provider has been opened.
    arkanime.get_website_url()

    headers = {"Referer": arkanime.website_origin}
    headers.update(_ask_headers())

    stream_url, subtitle_url = pm._resolve_stream(url, headers, False)
    if not stream_url:
        print_error("Could not resolve the stream URL, aborting.")
        pause()
        return

    print_success(f"Stream URL: [cyan]{stream_url}[/cyan]")

    try:
        domain = url.split("/")[2].lower()
    except IndexError:
        # Shorthand embeds ("montmyoboky:9646") have no host: the stream
        # lives on the provider, so its origin is the relevant one.
        domain = urlparse(arkanime.website_origin).hostname or ""

    title = "AutoFlix Mode Test"
    subtitle_paths = (
        pm._download_subtitles([subtitle_url]) if subtitle_url else []
    )

    results = []
    try:
        for player_code, mode in _launch_candidates(player_config):
            # The browser player has no executable to look up, it just needs
            # a working webbrowser.open().
            if player_code != "browser" and pm._get_player_executable(player_code) is None:
                print_warning(
                    f"Skipping [bold cyan]{player_code}[/bold cyan]: not installed."
                )
                continue

            print_divider()
            label = f"{player_code} / {mode}"
            active = pm.resolve_launch_mode(player_config, player_code) == mode
            marker = " [cyan](current default)[/cyan]" if active else ""
            print_header(f"Test: {label}{marker}")

            if not confirm("Launch this combination?"):
                print_info("Skipped.")
                results.append((player_code, mode, "skipped"))
                continue

            # The Referer depends on the mode: direct playback forwards the
            # embed page's own Referer, while the proxy mode derives one from
            # the config. Computing it per candidate keeps the tester faithful
            # to what play_video() actually sends.
            referer = pm._compute_referer(
                url, headers, player_config, domain, mode == pm.MODE_DIRECT
            )

            started = time.time()
            try:
                ok = pm._launch_player(
                    stream_url=stream_url,
                    headers=headers,
                    player_config=player_config,
                    player_code=player_code,
                    mode=mode,
                    is_mp4=player_config.get("ext") == "mp4",
                    referer=referer,
                    domain=domain,
                    title=title,
                    subtitle_paths=subtitle_paths,
                )
            except Exception as e:  # a broken player must not kill the tester
                print_error(f"Unexpected error: {e}")
                ok = False

            elapsed = time.time() - started
            if ok:
                print_success(f"{label} played in {elapsed:.1f}s")
                results.append((player_code, mode, "ok"))
            else:
                print_error(f"{label} failed after {elapsed:.1f}s")
                results.append((player_code, mode, "failed"))
    finally:
        for path in subtitle_paths:
            try:
                os.remove(path)
            except OSError:
                pass

    _report_mode_results(
        results,
        embed_url=url,
        stream_url=stream_url,
        headers=headers,
        player_config=player_config,
    )


def _report_mode_results(
    results: list,
    embed_url: str = "",
    stream_url: str = "",
    headers: dict = None,
    player_config: dict = None,
) -> None:
    """Summarise the test run and suggest the config to pin the winner."""
    print_divider()
    print_header("Results")
    for player_code, mode, status in results:
        icon = {"ok": "[green]OK[/green]", "failed": "[red]FAILED[/red]"}.get(
            status, "[yellow]skipped[/yellow]"
        )
        print_info(f"  {player_code} / {mode}: {icon}")

    working = {p for p, m, s in results if s == "ok" and m == "direct"}
    if working:
        print_success(
            "Direct mode works with: " + ", ".join(sorted(working))
        )
        print_info('Pin it in players_info.jsonc with:')
        entries = ", ".join(f'"{p}": "direct"' for p in sorted(working))
        print_info(f'  "modes": {{ {entries} }}')
    else:
        print_info("No combination played in direct mode, keep the proxy.")

    saved = _write_mode_report(
        results,
        embed_url=embed_url,
        stream_url=stream_url,
        headers=headers,
        player_config=player_config,
    )
    if saved:
        print_info(f"Report saved to: {saved}")
    pause()


def _write_mode_report(
    results: list,
    embed_url: str,
    stream_url: str,
    headers: dict,
    player_config: dict,
) -> str | None:
    """Persist the test run together with the URL that was tested.

    The verdict lines alone (``mpv / proxy: failed``) cannot be acted on: the
    next session has no way to know which embed produced them, so the failure
    is unreproducible. Everything needed to replay it goes in the same file.
    """
    matched = pm._match_player_config(embed_url)[1]
    return pm._write_dev_debug_report(
        [
            "[dev] embed URL: " + embed_url,
            "[dev] headers: " + json.dumps(headers or {}),
            "[dev] matched player: " + (matched or "none"),
            "[dev] player config: " + json.dumps(player_config or {}),
            "[dev] stream URL: " + str(stream_url),
            "[dev] ---- verdicts ----",
        ]
        + [f"[dev] {p} / {m}: {s}" for p, m, s in results]
    )