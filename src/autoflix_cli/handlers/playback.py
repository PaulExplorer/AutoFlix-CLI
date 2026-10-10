import urllib.parse

from ..cli_utils import (
    select_from_list,
    print_info,
    print_warning,
    print_error,
    print_success,
    print_divider,
    console,
)
from ..player_manager import play_video
from ..tracker import tracker
from ..scraping import player
from ..scraping import stream_probe
from ..scraping.player import PLAYER_EXTRACTORS, test_all_scrapers_verbose
from ..scraping.objects import Player
from rich.progress import Progress, SpinnerColumn, TextColumn
import json


AUTO_OPTION = "⚡ Auto - test all sources"


def _url_discriminator(url: str) -> str:
    """Short, human-readable part of an URL used to tell two apart."""
    parsed = urllib.parse.urlparse(url)
    host = parsed.netloc
    stem = parsed.path.rstrip("/").rsplit("/", 1)[-1]
    if stem and stem not in ("", "e", "embed", "index.html"):
        stem = stem.split(".")[0]
        return f"{host}/{stem}" if host else stem
    return host or url


def _disambiguate(names: list, urls: list) -> list:
    """Append something unique to the names that appear more than once.

    Several sources can resolve to the same embed name (a provider listing
    two entries on the same host), and identical rows in a menu are
    indistinguishable.
    """
    counts = {}
    for name in names:
        counts[name] = counts.get(name, 0) + 1

    labels = []
    for name, url in zip(names, urls):
        if counts[name] > 1:
            labels.append(f"{name} ({_url_discriminator(url)})")
        else:
            labels.append(name)
    return labels


def _source_labels(sources: list) -> list:
    """Display names of a list of ``Player`` objects."""
    return _disambiguate(
        [player.source_name(s.name, s.url) for s in sources],
        [s.url for s in sources],
    )


def _run_auto_probe(players: list, headers: dict) -> list:
    """Probe every source in parallel, reporting progress as they land."""
    done = 0
    total = len(players)

    def on_done(_source):
        nonlocal done
        done += 1
        progress.update(
            task, description=f"Testing sources... ({done}/{total})"
        )

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task(description="Testing sources...", total=None)
        return stream_probe.probe_sources(players, headers, on_done=on_done)


def _select_auto_source(players: list, headers: dict):
    """
    Resolve every source at once and let the user pick a working one.

    Returns the chosen ResolvedSource, or None when the user backs out or no
    source survives the probe (the caller then falls back to the plain list).
    """
    sources = _run_auto_probe(players, headers)
    working = [s for s in sources if s.ok]
    dead = [s for s in sources if not s.ok]

    print_divider()
    if not working:
        print_warning("No source could be resolved.")
    else:
        print_success(
            f"{len(working)}/{len(sources)} source(s) ready, best is "
            f"[cyan]{working[0].embed_name} ({working[0].quality_label})[/cyan]"
        )
    for source in dead:
        print_warning(f"{source.embed_name}: {source.error or 'unusable'}")

    # The best source sits at index 0, so Enter alone plays it while the
    # arrow keys still allow an explicit pick.
    working_names = _disambiguate(
        [s.embed_name for s in working], [s.embed_url for s in working]
    )
    options = [s.menu_label(name) for name, s in zip(working_names, working)]
    if dead:
        options.append("")
        options.append(f"── Unreachable ({len(dead)}) ──")
        options.extend(f"── ✗ {s.embed_name} · {s.error or 'unusable'}" for s in dead)
    options.append("← Back to source list")

    choice = select_from_list(options, "⚡ Select source (best quality first):")
    if choice >= len(working):
        return None
    return working[choice]


def _refresh_if_stale(source):
    """Re-extract a link that waited too long in the menu before launching.

    A failed re-extract does not cancel the source: the extraction may have
    hit a transient block while the original link is still alive, and the
    player reports a dead link far better than we can predict one.
    """
    if not source.is_stale:
        return source
    print_info("Link may have expired, resolving it again...")
    refreshed = stream_probe.resolve_source(
        source.embed_name, source.embed_url, source.headers
    )
    if refreshed.ok:
        return refreshed
    print_warning(f"{source.embed_name} is no longer resolvable ({refreshed.error}).")
    return source


def _print_dev_episode_context(
    episode: object,
    selected_player: object,
    headers: dict,
    series_url: str,
    season_url: str,
) -> None:
    """Show episode and embed details before resolving the stream."""
    embed_url = getattr(selected_player, "url", "")
    matched = next(
        (name for name in player.players if name in embed_url.lower()), "none"
    )
    config = player.players.get(matched, {})
    print_info(f"[dev] episode URL: {getattr(episode, 'url', '')}")
    print_info(f"[dev] series URL: {series_url}")
    print_info(f"[dev] season URL: {season_url}")
    print_info(f"[dev] embed URL: {embed_url}")
    print_info(f"[dev] headers: {json.dumps(headers or {})}")
    print_info(f"[dev] matched player: {matched}")
    print_info(f"[dev] extractor type: {config.get('type', 'unknown')}")


def play_episode_flow(
    provider_name: str,
    series_title: str,
    season_title: str,
    episode: object,
    series_url: str,
    season_url: str,
    logo_url: str = None,
    headers: dict = None,
    anilist_callback: callable = None,
) -> bool:
    """
    Handle the playback flow for a single episode:
    1. Check for players.
    2. Ask user to select a player.
    3. Play the video.
    4. Save progress if successful.
    5. Call optional AniList callback if successful.

    Returns:
        bool: True if playback was successful, False otherwise (back/cancel).
    """

    if not episode.players:
        print_warning("No players found for this episode.")
        return False

    dev_mode = tracker.get_developer_mode()
    supported_players = [p for p in episode.players if player.is_supported(p.url)]
    unsupported_players = [p for p in episode.players if not player.is_supported(p.url)]

    if not supported_players and not (dev_mode and unsupported_players):
        print_warning("No supported players found.")
        return False

    # Default headers if not provided
    if headers is None:
        headers = {}

    while True:
        # Player Selection Menu
        player_options = []
        player_map = []  # maps option index -> Player object

        for p, label in zip(supported_players, _source_labels(supported_players)):
            player_options.append(label)
            player_map.append(p)

        # In dev mode, show unsupported players with a clear marker
        if dev_mode and unsupported_players:
            player_options.append("")
            player_options.append("── Unsupported players (dev mode) ──")
            player_map.append(None)  # separator
            player_map.append(None)  # separator header
            for p in unsupported_players:
                player_options.append(
                    f"⚠ {player.source_name(p.name, p.url)} [NOT SUPPORTED]"
                )
                player_map.append(p)

        player_options.append("← Back")

        # Auto only makes sense with something to compare against.
        auto_index = None
        if len(supported_players) > 1:
            auto_index = 0
            player_options.insert(0, AUTO_OPTION)
            player_map.insert(0, AUTO_OPTION)

        player_idx = select_from_list(
            player_options,
            "🎮 Select Player:",
        )

        if player_idx == len(player_options) - 1:  # Back selected
            return False

        selected_player = player_map[player_idx]

        # --- Auto mode: test every source, then pick a working one ---
        resolved_source = None
        if auto_index is not None and player_idx == auto_index:
            resolved_source = _select_auto_source(supported_players, headers)
            if resolved_source is None:
                continue  # back to the source list
            resolved_source = _refresh_if_stale(resolved_source)
            if not resolved_source.ok:
                continue
            selected_player = Player(
                name=resolved_source.embed_name, url=resolved_source.embed_url
            )

        # Skip separator lines (user shouldn't land here, but guard anyway)
        if selected_player is None:
            continue

        # --- Dev mode: test unsupported players with all scrapers ---
        # Auto mode only ever picks supported sources, so the scraper sweep
        # (which exists to find a parser for an unknown embed) never applies.
        if resolved_source is None and not player.is_supported(selected_player.url):
            print_info(f"Testing {selected_player.name} with all available scrapers...")
            verbose_results = test_all_scrapers_verbose(selected_player.url, headers)
            for name, res in verbose_results.items():
                if res["ok"]:
                    print_success(f"{name} [{res['elapsed']:.1f}s] -> {res['stream_url']}")
                else:
                    print_info(f"{name} [{res['elapsed']:.1f}s] failed: {res['error']}")
            scraper_results = {
                n: r["stream_url"] for n, r in verbose_results.items() if r["ok"]
            }

            if scraper_results:
                scraper_names = list(scraper_results.keys())
                print_success(f"Found {len(scraper_names)} working scraper(s): {', '.join(scraper_names)}")
                scraper_opts = [f"{name} -> {scraper_results[name]}" for name in scraper_names]
                scraper_opts.append("← Back to player selection")
                scraper_idx = select_from_list(scraper_opts, "Select scraper to use:")

                if scraper_idx == len(scraper_names):
                    continue  # back to player list

                chosen_name = scraper_names[scraper_idx]
                stream_url = scraper_results[chosen_name]
                print_info(f"Using scraper '{chosen_name}' -> {stream_url}")

                # Create a fake player with the resolved stream URL
                selected_player = Player(name=f"{selected_player.name} [dev:{chosen_name}]", url=stream_url)
            else:
                print_warning("No scraper could extract a stream from this player.")
                print_info("This player is not supported and no existing scraper works with it.")
                continue

        # Construct title for player window
        window_title = f"{series_title} - {season_title} - {episode.title}"

        if dev_mode:
            _print_dev_episode_context(
                episode, selected_player, headers, series_url, season_url
            )

        success = play_video(
            selected_player.url,
            # A pre-resolved source carries the headers it was extracted with,
            # which are not always the episode-wide ones.
            headers=resolved_source.headers if resolved_source else headers,
            title=window_title,
            resolved=resolved_source,
        )

        if success:
            # Save Local Progress

            tracker.save_progress(
                provider=provider_name,
                series_title=series_title,
                season_title=season_title,
                episode_title=episode.title,
                series_url=series_url,
                season_url=season_url,
                episode_url=episode.url if hasattr(episode, "url") else "",
                logo_url=logo_url,
            )

            # AniList Hook
            if anilist_callback:
                anilist_callback()

            return True
        else:
            # Playback failed
            retry = select_from_list(
                ["Try another server/player", "← Back to main menu"],
                "What would you like to do?",
            )
            if retry == 1:  # Back
                return False
            # Loop continues to select list
