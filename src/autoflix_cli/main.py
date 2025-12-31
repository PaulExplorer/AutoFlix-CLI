from .scraping import wiflix, anime_sama, coflix, player, french_stream
from .scraping.objects import (
    WiflixMovie,
    WiflixSeriesSeason,
    SamaSeries,
    SamaSeason,
    CoflixSeries,
    CoflixSeason,
    CoflixMovie,
    Episode,
    EpisodeAccess,
    FrenchStreamMovie,
    FrenchStreamSeason,
)
from .cli_utils import (
    clear_screen,
    get_user_input,
    select_from_list,
    print_header,
    print_success,
    print_error,
    print_info,
    print_warning,
    console,
)
from . import proxy
from .tracker import tracker

from rich.progress import Progress, SpinnerColumn, TextColumn

import sys
import subprocess
import shutil
import os
import platform
import json
import threading
import time
import urllib


def get_vlc_path():
    """
    Find the VLC executable path.

    Returns:
        Path to VLC executable if found, None otherwise
    """
    # Check PATH first
    path = shutil.which("vlc")
    if path:
        return path

    if platform.system() == "Windows":
        # Check Registry
        try:
            import winreg

            for key_path in [
                r"SOFTWARE\VideoLAN\VLC",
                r"SOFTWARE\WOW6432Node\VideoLAN\VLC",
            ]:
                try:
                    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path) as key:
                        install_dir = winreg.QueryValueEx(key, "InstallDir")[0]
                        exe_path = os.path.join(install_dir, "vlc.exe")
                        if os.path.exists(exe_path):
                            return exe_path
                except FileNotFoundError:
                    continue
        except Exception:
            pass

        # Check common paths
        common_paths = [
            os.path.expandvars(r"%ProgramFiles%\VideoLAN\VLC\vlc.exe"),
            os.path.expandvars(r"%ProgramFiles(x86)%\VideoLAN\VLC\vlc.exe"),
        ]
        for p in common_paths:
            if os.path.exists(p):
                return p

    return None


def handle_player_error(context: str = "player") -> int:
    """
    Handle player errors and ask user what they want to do.

    Args:
        context: Context of the error (default: "player")

    Returns:
        User's choice index: 0 = try another, 1 = back
    """
    return select_from_list(
        ["Try another player", "← Back"],
        f"The {context} failed. What would you like to do?",
    )


def play_video(url: str, headers: dict, title: str = "AutoFlix Stream") -> bool:
    """
    Attempt to play a video with the chosen player.

    Args:
        url: Video player URL
        headers: HTTP headers for the request
        title: Title of the video to display in the player

    Returns:
        True if playback succeeded, False otherwise
    """
    print_info(f"Resolving stream for: [cyan]{url}[/cyan]")

    if hasattr(player, "new_url") and isinstance(player.new_url, dict):
        for old, new in player.new_url.items():
            url = url.replace(old, new)

    # Determine player configuration
    player_config = {}
    for player_name, config in player.players.items():
        if player_name in url.lower():
            player_config = config
            break

    try:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            progress.add_task(description="Getting stream URL...", total=None)
            stream_url = player.get_hls_link(url, headers)
            if stream_url and stream_url.startswith("/"):
                stream_url = (
                    "https://"
                    + url.removeprefix("https://").removeprefix("http://").split("/")[0]
                    + stream_url
                )
    except Exception as e:
        print_error(f"Error resolving stream URL: {e}")
        return False

    if not stream_url:
        print_error("Could not resolve stream URL.")
        return False

    print_success(f"Stream URL: [cyan]{stream_url}[/cyan]")

    while True:  # Loop to allow retrying with another player
        players = ["mpv", "vlc", "← Back"]
        player_choice = select_from_list(players, "🎮 Select video player:")

        if players[player_choice] == "← Back":
            return False

        player_name = players[player_choice]
        player_executable = None

        # --- 1. Preparation of Headers & Referer for both players ---
        # Calculate Referer
        try:
            domain = url.split("/")[2].lower()
            referer = f"https://{domain}"
            if player_config.get("referrer") == "full":
                referer = url
            elif player_config.get("referrer") == "path":
                referer = f"https://{domain}/"
            elif isinstance(player_config.get("referrer"), str):
                referer = player_config.get("referrer")

            referer = f"{referer}/"
        except IndexError:
            referer = ""

        default_ua = (
            "Mozilla/5.0 (X11; Linux x86_64; rv:144.0) Gecko/20100101 Firefox/144.0"
        )
        user_agent = headers.get("User-Agent", default_ua)

        if player_name == "vlc":
            player_executable = get_vlc_path()
            if not player_executable:
                print_error("VLC not found. Please install it or add it to your PATH.")
                retry = handle_player_error("VLC")
                if retry == 1:  # Back
                    return False
                continue
        else:
            player_executable = shutil.which(player_name)
            if not player_executable:
                print_error(f"{player_name} is not installed or not in PATH.")
                retry = handle_player_error(player_name)
                if retry == 1:  # Back
                    return False
                continue

        # Determine Launch Mode from config
        mode = player_config.get("mode", "proxy")  # Default to proxy

        if mode == "proxy":
            print_info(
                f"Launching [bold cyan]{player_name}[/bold cyan] via Proxy ({player_executable})..."
            )

            # Construct Proxy URL
            # We need to pass the headers to the proxy
            # Combine all necessary headers
            proxy_headers = headers.copy()
            if referer:
                proxy_headers["Referer"] = referer

            # Add specific headers from config
            if player_config.get("alt-used") is True:
                proxy_headers["Alt-Used"] = domain

            sec_headers = player_config.get("sec_headers")
            if sec_headers:
                # Parse sec_headers string if needed, or just add them
                # For simplicity in this proxy implementation, we might need to parse them if they are in string format "Key:Value;Key2:Value2"
                if isinstance(sec_headers, str):
                    for part in sec_headers.split(";"):
                        if ":" in part:
                            k, v = part.split(":", 1)
                            proxy_headers[k.strip()] = v.strip()

            headers_json = json.dumps(proxy_headers)
            encoded_url = urllib.parse.quote(stream_url)
            encoded_headers = urllib.parse.quote(headers_json)

            local_stream_url = f"http://127.0.0.1:5000/stream?url={encoded_url}&headers={encoded_headers}"

            if "ext" in player_config:
                local_stream_url += f"&ext={player_config['ext']}"

            try:
                cmd = [player_executable, local_stream_url]
                if player_name == "vlc":
                    cmd.append(f"--meta-title={title}")
                elif player_name == "mpv":
                    cmd.append(f"--title={title}")

                subprocess.run(cmd, check=True)
                print_success("Playback completed successfully!")
                return True
            except Exception as e:
                print_error(f"Error running player via proxy: {e}")

        elif mode == "direct":
            print_info(
                f"Launching [bold cyan]{player_name}[/bold cyan] directly ({player_executable})..."
            )
            try:
                if player_name == "vlc":
                    # VLC Command construction
                    cmd = [
                        player_executable,
                        stream_url,
                        f":http-referrer={referer}",
                        f":http-user-agent={user_agent}",
                        f"--meta-title={title}",
                    ]
                    subprocess.run(cmd, check=True)
                else:
                    # MPV Command construction
                    headers_mpv = f"Origin: {referer.split('/')[2]}"
                    add_default_sec_headers = False

                    if player_config.get("alt-used") is True:
                        headers_mpv = f"Alt-Used: {domain};" + headers_mpv

                    sec_headers = player_config.get("sec_headers")
                    if sec_headers:
                        if isinstance(sec_headers, str):
                            headers_mpv += ";" + sec_headers
                        elif isinstance(sec_headers, bool) and sec_headers is True:
                            add_default_sec_headers = True
                    else:
                        add_default_sec_headers = True

                    if add_default_sec_headers:
                        headers_mpv += ";Sec-Fetch-Dest: iframe;Sec-Fetch-Mode: navigate;Sec-Fetch-Site: same-origin"

                    if player_config.get("no-header") is True:
                        headers_mpv = ""

                    print_info(f"Headers: {headers_mpv}")

                    cmd = [
                        player_executable,
                        f'--referrer="{referer}"',
                        f'--user-agent="{user_agent}"',
                        f'--http-header-fields="{headers_mpv}"',
                        f'--title="{title}"',
                        stream_url,
                    ]
                    subprocess.run(cmd, check=True)

                print_success("Playback completed successfully!")
                return True

            except subprocess.CalledProcessError as e:
                print_error(f"Error running player: {e}")
                # Retry logic below
            except Exception as e:
                print_error(f"An unexpected error occurred: {e}")
                # Retry logic below

        # Common retry logic
        retry = select_from_list(
            [
                "Try another player",
                "Retry with same player",
                "← Back",
            ],
            "The player failed. What would you like to do?",
        )
        if retry == 0:  # Try another player
            continue
        elif retry == 1:  # Retry with same player
            continue
        else:  # Back
            return False


def select_and_play_player(supported_players: list, referer: str, title: str) -> bool:
    """
    Let user select a player and attempt playback with retry logic.

    Args:
        supported_players: List of supported player objects
        referer: HTTP Referer header value
        title: Title of the video

    Returns:
        True if playback succeeded, False otherwise
    """
    while True:
        player_idx = select_from_list(
            [p.name for p in supported_players] + ["← Back"], "🎮 Select Player:"
        )

        if player_idx == len(supported_players):  # Back
            return False

        success = play_video(
            supported_players[player_idx].url,
            headers={"Referer": referer},
            title=title,
        )

        if success:
            return True
        else:
            # Playback failed, ask if they want to retry
            retry = select_from_list(
                ["Try another server/player", "← Back to main menu"],
                "What would you like to do?",
            )
            if retry == 1:  # Back
                return False
            # Otherwise continue the loop to choose another player


def handle_wiflix():
    """Handle Wiflix provider flow."""
    print_header("🎬 Wiflix")
    query = get_user_input("Search query")

    print_info(f"Searching for: [cyan]{query}[/cyan]")
    results = wiflix.search(query)

    if not results:
        print_warning("No results found.")
        return

    choice_idx = select_from_list(
        [f"{r.title} ({', '.join(r.genres)})" for r in results], "📺 Search Results:"
    )
    selection = results[choice_idx]

    print_info(f"Loading [cyan]{selection.title}[/cyan]...")
    content = wiflix.get_content(selection.url)

    if isinstance(content, WiflixMovie):
        console.print(f"\n[bold]🎬 Movie:[/bold] [cyan]{content.title}[/cyan]")
        if not content.players:
            print_warning("No players found.")
            return
        supported_players = [p for p in content.players if player.is_supported(p.url)]
        if not supported_players:
            print_warning("No supported players found.")
            return

        select_and_play_player(supported_players, wiflix.website_origin, content.title)

    elif isinstance(content, WiflixSeriesSeason):
        console.print(
            f"\n[bold]📺 Series:[/bold] [cyan]{content.title} - {content.season}[/cyan]"
        )

        # episodes is a dict {lang: [Episode]}
        langs = list(content.episodes.keys())
        if not langs:
            print_warning("No episodes found.")
            return

        lang_idx = select_from_list(langs, "🌍 Select Language:")
        selected_lang = langs[lang_idx]
        episodes = content.episodes[selected_lang]

        ep_idx = select_from_list([e.title for e in episodes], "📺 Select Episode:")

        while True:
            selected_episode = episodes[ep_idx]

            if not selected_episode.players:
                print_warning("No players found for this episode.")
                return

            supported_players = [
                p for p in selected_episode.players if player.is_supported(p.url)
            ]
            if not supported_players:
                print_warning("No supported players found.")
                return

            success = select_and_play_player(
                supported_players,
                wiflix.website_origin,
                f"{content.title} - {selected_episode.title}",
            )

            if success:
                tracker.save_progress(
                    provider="Wiflix",
                    series_title=content.title,
                    season_title=content.season,
                    episode_title=selected_episode.title,
                    series_url=content.url,
                    season_url=content.url,
                    episode_url="",
                    logo_url=content.img,
                )

                if ep_idx + 1 < len(episodes):
                    next_ep = episodes[ep_idx + 1]
                    choice = select_from_list(
                        ["Yes", "No"], f"Play next episode: {next_ep.title}?"
                    )
                    if choice == 0:
                        ep_idx += 1
                        continue
            break


def handle_anime_sama():
    """Handle Anime-Sama provider flow."""
    anime_sama.get_website_url()

    print_header("🎌 Anime-Sama")
    query = get_user_input("Search query")

    print_info(f"Searching for: [cyan]{query}[/cyan]")
    results = anime_sama.search(query)

    if not results:
        print_warning("No results found.")
        return

    choice_idx = select_from_list(
        [f"{r.title} ({', '.join(r.genres)})" for r in results], "📺 Search Results:"
    )
    selection = results[choice_idx]

    print_info(f"Loading [cyan]{selection.title}[/cyan]...")
    series = anime_sama.get_series(selection.url)

    if not series.seasons:
        print_warning("No seasons found.")
        return

    # Check for saved progress for this specific series
    saved_progress = tracker.get_series_progress("Anime-Sama", series.title)
    if saved_progress:
        choice = select_from_list(
            [
                f"Resume {saved_progress['season_title']} - {saved_progress['episode_title']}",
                "Browse Seasons",
            ],
            f"Found saved progress for {series.title}:",
        )
        if choice == 0:
            resume_anime_sama(saved_progress)
            return

    season_idx = select_from_list(
        [s.title for s in series.seasons], "📺 Select Season:"
    )
    selected_season_access = series.seasons[season_idx]

    print_info(f"Loading [cyan]{selected_season_access.title}[/cyan]...")
    season = anime_sama.get_season(selected_season_access.url)

    # episodes is dict {lang: [Episode]}
    langs = list(season.episodes.keys())
    if not langs:
        print_warning("No episodes found.")
        return

    lang_idx = select_from_list(langs, "🌍 Select Language:")
    selected_lang = langs[lang_idx]
    episodes = season.episodes[selected_lang]

    ep_idx = select_from_list([e.title for e in episodes], "📺 Select Episode:")

    while True:
        selected_episode = episodes[ep_idx]

        if not selected_episode.players:
            print_warning("No players found for this episode.")
            return

        supported_players = [
            p for p in selected_episode.players if player.is_supported(p.url)
        ]
        if not supported_players:
            print_warning("No supported players found.")
            return

        # Loop to allow retrying with another player
        playback_success = False
        while True:
            player_idx = select_from_list(
                [
                    f"{p.name} : {p.url.split('/')[2].split('.')[-2]}"
                    for p in supported_players
                ]
                + ["← Back"],
                "🎮 Select Player:",
            )

            if player_idx == len(supported_players):  # Back
                return

            success = play_video(
                supported_players[player_idx].url,
                headers={"Referer": anime_sama.website_origin},
                title=f"{series.title} - {season.title} - {selected_episode.title}",
            )

            if success:
                # Save progress
                tracker.save_progress(
                    provider="Anime-Sama",
                    series_title=series.title,
                    season_title=season.title,
                    episode_title=selected_episode.title,
                    series_url=series.url,
                    season_url=selected_season_access.url,
                    episode_url="",  # content.episode_url if available
                    logo_url=series.img,
                )

                playback_success = True
                break  # Playback succeeded, exit player loop
            else:
                # Playback failed, ask if they want to retry
                retry = select_from_list(
                    ["Try another server/player", "← Back to main menu"],
                    "What would you like to do?",
                )
                if retry == 1:  # Back
                    return
                # Otherwise continue the loop to choose another player

        if playback_success:
            if ep_idx + 1 < len(episodes):
                next_ep = episodes[ep_idx + 1]
                choice = select_from_list(
                    ["Yes", "No"], f"Play next episode: {next_ep.title}?"
                )
                if choice == 0:
                    ep_idx += 1
                    continue
            break


def handle_coflix():
    """Handle Coflix provider flow."""
    coflix.get_website_url()

    print_header("🎬 Coflix")
    query = get_user_input("Search query")

    print_info(f"Searching for: [cyan]{query}[/cyan]")
    results = coflix.search(query)

    if not results:
        print_warning("No results found.")
        return

    choice_idx = select_from_list([f"{r.title}" for r in results], "📺 Search Results:")
    selection = results[choice_idx]

    print_info(f"Loading [cyan]{selection.title}[/cyan]...")
    content = coflix.get_content(selection.url)

    if isinstance(content, CoflixMovie):
        console.print(f"\n[bold]🎬 Movie:[/bold] [cyan]{content.title}[/cyan]\n")
        if not content.players:
            print_warning("No players found.")
            return
        supported_players = [p for p in content.players if player.is_supported(p.url)]
        if not supported_players:
            print_warning("No supported players found.")
            return

        # Loop to allow retrying with another player
        while True:
            player_idx = select_from_list(
                [f"Player : {p.name}" for p in supported_players] + ["← Back"],
                "🎮 Select Player:",
            )

            if player_idx == len(supported_players):  # Back
                return

            success = play_video(
                supported_players[player_idx].url,
                headers={
                    "Referer": "https://lecteurvideo.com/",
                },
                title=content.title,
            )

            if success:
                tracker.save_progress(
                    provider="Coflix",
                    series_title=content.title,
                    season_title="Movie",
                    episode_title="Movie",
                    series_url=content.url,
                    season_url=content.url,
                    episode_url=content.url,
                    logo_url=content.img,
                )

                return  # Playback succeeded, exit
            else:
                # Playback failed, ask if they want to retry
                retry = select_from_list(
                    ["Try another server/player", "← Back to main menu"],
                    "What would you like to do?",
                )
                if retry == 1:  # Back
                    return
                # Otherwise continue the loop to choose another player

    elif isinstance(content, CoflixSeries):
        console.print(f"\n[bold]📺 Series:[/bold] [cyan]{content.title}[/cyan]\n")

        if not content.seasons:
            print_warning("No seasons found.")
            return

        # Check for saved progress for this specific series
        saved_progress = tracker.get_series_progress("Coflix", content.title)
        if saved_progress:
            choice = select_from_list(
                [
                    f"Resume {saved_progress['season_title']} - {saved_progress['episode_title']}",
                    "Browse Seasons",
                ],
                f"Found saved progress for {content.title}:",
            )
            if choice == 0:
                resume_coflix(saved_progress)
                return

        season_idx = select_from_list(
            [s.title for s in content.seasons], "📺 Select Season:"
        )
        selected_season_access = content.seasons[season_idx]

        print_info(f"Loading [cyan]{selected_season_access.title}[/cyan]...")
        season = coflix.get_season(selected_season_access.url)

        if not season.episodes:
            print_warning("No episodes found.")
            return

        ep_idx = select_from_list(
            [e.title for e in season.episodes], "📺 Select Episode:"
        )

        while True:
            selected_episode = season.episodes[ep_idx]

            # Get episode links and filter for supported players
            links = coflix.get_episode(selected_episode.url).players
            supported_links = [link for link in links if player.is_supported(link.url)]

            if not supported_links:
                print_warning("No supported players found.")
                return

            # Loop to allow retrying with another player
            playback_success = False
            while True:
                player_idx = select_from_list(
                    [f"Player : {link.name}" for link in supported_links] + ["← Back"],
                    "🎮 Select Player:",
                )

                if player_idx == len(supported_links):  # Back
                    return

                success = play_video(
                    supported_links[player_idx].url,
                    headers={
                        "Referer": "https://lecteurvideo.com/",
                    },
                    title=f"{selected_season_access.title} - {selected_episode.title}",
                )

                if success:
                    tracker.save_progress(
                        provider="Coflix",
                        series_title=content.title,
                        season_title=selected_season_access.title,
                        episode_title=selected_episode.title,
                        series_url=content.url,
                        season_url=selected_season_access.url,
                        episode_url=selected_episode.url,
                        logo_url=content.img,
                    )

                    playback_success = True
                    break  # Playback succeeded, exit player loop
                else:
                    # Playback failed, ask if they want to retry
                    retry = select_from_list(
                        ["Try another server/player", "← Back to main menu"],
                        "What would you like to do?",
                    )
                    if retry == 1:  # Back
                        return
                    # Otherwise continue the loop to choose another player

            if playback_success:
                if ep_idx + 1 < len(season.episodes):
                    next_ep = season.episodes[ep_idx + 1]
                    choice = select_from_list(
                        ["Yes", "No"], f"Play next episode: {next_ep.title}?"
                    )
                    if choice == 0:
                        ep_idx += 1
                        continue
                break


def handle_french_stream():
    """Handle French-Stream provider flow."""
    print_header("🇫🇷 French-Stream")
    query = get_user_input("Search query")

    print_info(f"Searching for: [cyan]{query}[/cyan]")
    results = french_stream.search(query)

    if not results:
        print_warning("No results found.")
        return

    choice_idx = select_from_list([r.title for r in results], "📺 Search Results:")
    selection = results[choice_idx]

    print_info(f"Loading [cyan]{selection.title}[/cyan]...")
    content = french_stream.get_content(selection.url)

    if isinstance(content, FrenchStreamMovie):
        console.print(f"\n[bold]🎬 Movie:[/bold] [cyan]{content.title}[/cyan]\n")
        if not content.players:
            print_warning("No players found.")
            return
        supported_players = [p for p in content.players if player.is_supported(p.url)]
        if not supported_players:
            print_warning("No supported players found.")
            return

        select_and_play_player(
            supported_players, french_stream.website_origin, content.title
        )

    elif isinstance(content, FrenchStreamSeason):
        console.print(f"\n[bold]📺 Series:[/bold] [cyan]{content.title}[/cyan]\n")

        # episodes is a dict {lang: [Episode]}
        langs = list(content.episodes.keys())
        if not langs:
            print_warning("No episodes found.")
            return

        # Check for saved progress for this specific series
        saved_progress = tracker.get_series_progress("French-Stream", content.title)
        if saved_progress:
            choice = select_from_list(
                [
                    f"Resume {saved_progress['season_title'].replace(content.title, '').strip()} - {saved_progress['episode_title']}",
                    "Browse Languages",
                ],
                f"Found saved progress for {content.title}:",
            )
            if choice == 0:
                resume_french_stream(saved_progress)
                return

        lang_idx = select_from_list(langs, "🌍 Select Language:")
        selected_lang = langs[lang_idx]
        episodes = content.episodes[selected_lang]

        ep_idx = select_from_list([e.title for e in episodes], "📺 Select Episode:")

        while True:
            selected_episode = episodes[ep_idx]

            if not selected_episode.players:
                print_warning("No players found for this episode.")
                return

            supported_players = [
                p for p in selected_episode.players if player.is_supported(p.url)
            ]
            if not supported_players:
                print_warning("No supported players found.")
                return

            success = select_and_play_player(
                supported_players,
                french_stream.website_origin,
                f"{content.title} - {selected_episode.title}",
            )

            if success:
                tracker.save_progress(
                    provider="French-Stream",
                    series_title=content.title,
                    season_title=content.title,
                    episode_title=selected_episode.title,
                    series_url=content.url,
                    season_url=content.url,
                    episode_url="",
                    logo_url=None,
                )

                if ep_idx + 1 < len(episodes):
                    next_ep = episodes[ep_idx + 1]
                    choice = select_from_list(
                        ["Yes", "No"], f"Play next episode: {next_ep.title}?"
                    )
                    if choice == 0:
                        ep_idx += 1
                        continue
            break


def resolve_url(url: str, base_url: str) -> str:
    """Resolve URL: keep if absolute (http/https), else prepend base_url."""
    if not url:
        return ""
    if url.startswith("http://") or url.startswith("https://"):
        return url
    return base_url.rstrip("/") + "/" + url.lstrip("/")


def resume_anime_sama(data):
    """Resume Anime-Sama playback."""
    anime_sama.get_website_url()

    print_info(
        f"Resuming [cyan]{data['series_title']} - {data['season_title']}[/cyan]..."
    )

    data["series_url"] = resolve_url(data["series_url"], anime_sama.website_origin)
    data["season_url"] = resolve_url(data["season_url"], anime_sama.website_origin)
    if "episode_url" in data:
        data["episode_url"] = resolve_url(
            data["episode_url"], anime_sama.website_origin
        )

    # We go directly to season URL (skipping series page)
    # Check if season_url is valid, if empty fall back to series_url logic (not implemented here for simplicity)
    if not data["season_url"]:
        print_error("Cannot resume: missing season URL.")
        return

    season = anime_sama.get_season(data["season_url"])

    langs = list(season.episodes.keys())
    if not langs:
        print_warning("No episodes found.")
        return

    # If only one language, pick it. If multiple, ask.
    if len(langs) == 1:
        selected_lang = langs[0]
    else:
        # Try to guess or ask?
        # Ideally we saved language. Since we didn't, we ask.
        lang_idx = select_from_list(langs, "🌍 Select Language:")
        selected_lang = langs[lang_idx]

    episodes = season.episodes[selected_lang]

    # Find the episode index
    start_ep_idx = 0
    saved_ep_title = data["episode_title"]

    for i, ep in enumerate(episodes):
        if ep.title == saved_ep_title:
            start_ep_idx = i
            break

    # Propose to continue (next episode) or watch again
    options = [
        (
            f"Continue (Next: {episodes[start_ep_idx+1].title})"
            if start_ep_idx + 1 < len(episodes)
            else "No next episode"
        ),
        f"Watch again ({saved_ep_title})",
        "Cancel",
    ]
    choice = select_from_list(options, "What would you like to do?")

    if choice == 2:  # Cancel
        return
    elif choice == 0:  # Continue
        if start_ep_idx + 1 < len(episodes):
            start_ep_idx += 1
        else:
            print_warning("No next episode found.")
            return
    # choice 1 is watch again -> keep start_ep_idx

    # Start loop
    ep_idx = start_ep_idx

    # Standard playback loop (copied from handle_anime_sama but simplified)
    while True:
        selected_episode = episodes[ep_idx]
        if not selected_episode.players:
            print_warning("No players found for this episode.")
            return

        supported_players = [
            p for p in selected_episode.players if player.is_supported(p.url)
        ]
        if not supported_players:
            print_warning("No supported players found.")
            return

        playback_success = False
        while True:
            player_idx = select_from_list(
                [
                    f"{p.name} : {p.url.split('/')[2].split('.')[-2]}"
                    for p in supported_players
                ]
                + ["← Back"],
                "🎮 Select Player:",
            )

            if player_idx == len(supported_players):
                return

            success = play_video(
                supported_players[player_idx].url,
                headers={"Referer": anime_sama.website_origin},
                title=f"{data['series_title']} - {season.title} - {selected_episode.title}",
            )

            if success:
                tracker.save_progress(
                    provider="Anime-Sama",
                    series_title=data["series_title"],
                    season_title=season.title,
                    episode_title=selected_episode.title,
                    series_url=data["series_url"],
                    season_url=data["season_url"],
                    episode_url="",
                    logo_url=data.get("logo_url"),
                )
                playback_success = True
                break
            else:
                retry = select_from_list(
                    ["Try another server/player", "← Back to main menu"],
                    "What would you like to do?",
                )
                if retry == 1:
                    return

        if playback_success:
            if ep_idx + 1 < len(episodes):
                next_ep = episodes[ep_idx + 1]
                choice = select_from_list(
                    ["Yes", "No"], f"Play next episode: {next_ep.title}?"
                )
                if choice == 0:
                    ep_idx += 1
                    continue
            break


def resume_coflix(data):
    """Resume Coflix playback."""
    coflix.get_website_url()

    print_info(f"Resuming [cyan]{data['series_title']}[/cyan]...")

    data["series_url"] = resolve_url(data["series_url"], coflix.website_origin)
    data["season_url"] = resolve_url(data["season_url"], coflix.website_origin)
    if "episode_url" in data:
        data["episode_url"] = resolve_url(data["episode_url"], coflix.website_origin)

    # Determine if Movie or Series based on saved data?
    # CoflixMovie saved episode_title="Movie".
    if data["episode_title"] == "Movie":
        # Resume MOVIE
        content = coflix.get_content(data["series_url"])
        if not isinstance(content, CoflixMovie):
            print_error("Saved data mismatch (expected Movie).")
            return
        # Just play it
        if not content.players:
            return
        supported = [p for p in content.players if player.is_supported(p.url)]
        if not supported:
            return

        while True:
            idx = select_from_list(
                [f"Player : {p.name}" for p in supported] + ["← Back"],
                "🎮 Select Player:",
            )
            if idx == len(supported):
                return
            success = play_video(
                supported[idx].url,
                headers={"Referer": "https://lecteurvideo.com/"},
                title=content.title,
            )
            if success:
                return
            if select_from_list(["Retry", "Back"], "Action?") == 1:
                return

    else:
        # Resume SERIES
        # We need to get season. We have season_url.
        season = coflix.get_season(data["season_url"])
        if not season.episodes:
            return

        start_ep_idx = 0
        for i, ep in enumerate(season.episodes):
            if ep.title == data["episode_title"]:
                start_ep_idx = i
                break

        options = [
            (
                f"Continue (Next: {season.episodes[start_ep_idx+1].title})"
                if start_ep_idx + 1 < len(season.episodes)
                else "No next episode"
            ),
            f"Watch again ({data['episode_title']})",
            "Cancel",
        ]
        choice = select_from_list(options, "What would you like to do?")
        if choice == 2:
            return
        elif choice == 0:
            if start_ep_idx + 1 < len(season.episodes):
                start_ep_idx += 1
            else:
                return  # No next

        ep_idx = start_ep_idx
        while True:
            selected_episode = season.episodes[ep_idx]
            links = coflix.get_episode(selected_episode.url).players
            supported = [l for l in links if player.is_supported(l.url)]
            if not supported:
                return

            playback_success = False
            while True:
                idx = select_from_list(
                    [f"Player : {l.name}" for l in supported] + ["← Back"],
                    "🎮 Select Player:",
                )
                if idx == len(supported):
                    return
                success = play_video(
                    supported[idx].url,
                    headers={"Referer": "https://lecteurvideo.com/"},
                    title=f"{data['season_title']} - {selected_episode.title}",
                )
                if success:
                    tracker.save_progress(
                        provider="Coflix",
                        series_title=data["series_title"],
                        season_title=data["season_title"],
                        episode_title=selected_episode.title,
                        series_url=data["series_url"],
                        season_url=data["season_url"],
                        episode_url=selected_episode.url,
                        logo_url=data.get("logo_url"),
                    )
                    playback_success = True
                    break
                if select_from_list(["Retry", "Back"], "Action?") == 1:
                    return

            if playback_success:
                if ep_idx + 1 < len(season.episodes):
                    if (
                        select_from_list(
                            ["Yes", "No"],
                            f"Play next: {season.episodes[ep_idx+1].title}?",
                        )
                        == 0
                    ):
                        ep_idx += 1
                        continue
                break


def resume_french_stream(data):
    """Resume French-Stream playback."""
    print_info(f"Resuming [cyan]{data['series_title']}[/cyan]...")

    data["series_url"] = resolve_url(data["series_url"], french_stream.website_origin)
    data["season_url"] = resolve_url(data["season_url"], french_stream.website_origin)
    if "episode_url" in data:
        data["episode_url"] = resolve_url(
            data["episode_url"], french_stream.website_origin
        )

    # Similar to Coflix logic (Series vs Movie) but struct is different
    # Movie doesn't have "season_url" distinct usually, but we saved it.

    # We load content from SERIES URL (or movie url)
    content = french_stream.get_content(data["series_url"])

    if isinstance(content, FrenchStreamMovie):
        if not content.players:
            return
        supported = [p for p in content.players if player.is_supported(p.url)]
        select_and_play_player(supported, french_stream.website_origin, content.title)
        return

    elif isinstance(content, FrenchStreamSeason):
        # We need to find the correct language list
        # data['season_url'] might just be the series url.
        # But wait, FrenchStreamSeason episodes = dict[lang, list]
        langs = list(content.episodes.keys())
        if not langs:
            return

        # Ask language
        if len(langs) == 1:
            lang = langs[0]
        else:
            lang = langs[select_from_list(langs, "🌍 Select Language:")]

        episodes = content.episodes[lang]

        start_ep_idx = 0
        for i, ep in enumerate(episodes):
            if ep.title == data["episode_title"]:
                start_ep_idx = i
                break

        options = [
            (
                f"Continue (Next: {episodes[start_ep_idx+1].title})"
                if start_ep_idx + 1 < len(episodes)
                else "No next episode"
            ),
            f"Watch again ({data['episode_title']})",
            "Cancel",
        ]
        choice = select_from_list(options, "What would you like to do?")
        if choice == 2:
            return
        elif choice == 0:
            if start_ep_idx + 1 < len(episodes):
                start_ep_idx += 1
            else:
                return

        ep_idx = start_ep_idx
        while True:
            selected_episode = episodes[ep_idx]
            if not selected_episode.players:
                return
            supported = [
                p for p in selected_episode.players if player.is_supported(p.url)
            ]

            success = select_and_play_player(
                supported,
                french_stream.website_origin,
                f"{content.title} - {selected_episode.title}",
            )

            if success:
                tracker.save_progress(
                    provider="French-Stream",
                    series_title=content.title,
                    season_title=content.title,
                    episode_title=selected_episode.title,
                    series_url=content.url,
                    season_url=content.url,
                    episode_url="",
                    logo_url=None,
                )
                if ep_idx + 1 < len(episodes):
                    if (
                        select_from_list(
                            ["Yes", "No"], f"Play next: {episodes[ep_idx+1].title}?"
                        )
                        == 0
                    ):
                        ep_idx += 1
                        continue
            break


def handle_resume(data):
    """Dispatch resume to provider."""
    provider = data["provider"]
    if provider == "Anime-Sama":
        resume_anime_sama(data)
    elif provider == "Coflix":
        resume_coflix(data)
    elif provider == "French-Stream":
        resume_french_stream(data)
    # Wiflix resume not implemented yet or similar to French-Stream
    elif provider == "Wiflix":
        print_warning("Resume for Wiflix not optimized yet.")


def handle_history():
    """Display history list and allow resume/delete."""
    while True:
        clear_screen()
        print_header("📜 My History")

        history = tracker.get_history()
        if not history:
            print_warning("No history found.")
            input("\nPress Enter to go back...")
            return

        options = []
        for entry in history:
            provider = entry["provider"]
            series = entry["series_title"]
            season = entry["season_title"]
            episode = entry["episode_title"]

            if provider == "Coflix":
                if season == "Movie" or episode == "Movie":
                    text = f"[{provider}] {series} (Movie)"
                else:
                    # Remove series title from season if present (e.g. "Series - Season X")
                    clean_season = season.replace(series, "").strip(" -")
                    # If it becomes empty (season was just series title), fallback or keep it contextually?
                    # Ideally season should be "Season X". If empty, maybe it was just "SeriesName".
                    if not clean_season:
                        clean_season = season
                    text = f"[{provider}] {series} - {clean_season} - {episode}"

            elif provider == "French-Stream":
                # Similar logic: "Series - Saison X" -> "Saison X"
                clean_season = season.replace(series, "").strip(" -")
                if not clean_season:
                    clean_season = season
                text = f"[{provider}] {series} - {clean_season} - {episode}"

            else:
                # Anime-Sama and others
                text = f"[{provider}] {series} - {season} - {episode}"

            options.append(text)

        options.append("← Back")

        choice_idx = select_from_list(options, "Select an item to manage:")

        if choice_idx == len(options) - 1:  # Back
            return

        selected_entry = history[choice_idx]

        action = select_from_list(
            ["▶ Resume", "🗑 Delete", "← Cancel"],
            f"Action for {selected_entry['series_title']}?",
        )

        if action == 0:  # Resume
            handle_resume(selected_entry)
            return
        elif action == 1:  # Delete
            tracker.delete_history_item(
                selected_entry["provider"], selected_entry["series_title"]
            )
            print_success("Entry deleted.")
            time.sleep(1)
            # Loop continues to refresh list


def main():
    """Main application loop."""
    # Start proxy server
    proxy.start_proxy_server()

    while True:
        clear_screen()
        print_header("🎬 AutoFlix CLI")

        last_watch = tracker.get_last_global()
        options = []
        resume_idx = -1

        if last_watch:
            series = last_watch["series_title"]
            ep = last_watch["episode_title"]
            options.append(f"▶ Resume {series} ({ep})")
            resume_idx = 0

        options.append("📜 My History")
        history_idx = len(options) - 1

        options.append("🌍 Browse Providers")
        browse_idx = len(options) - 1

        options.append("Exit")
        exit_idx = len(options) - 1

        choice_idx = select_from_list(options, "What would you like to do?")

        if last_watch and choice_idx == resume_idx:
            handle_resume(last_watch)
            continue

        if choice_idx == history_idx:
            handle_history()
            continue

        if choice_idx == browse_idx:
            while True:
                provider_choice = select_from_list(
                    ["Anime-Sama", "Coflix", "French-Stream", "← Back"],
                    "Select Provider:",
                )
                if provider_choice == 0:
                    handle_anime_sama()
                elif provider_choice == 1:
                    handle_coflix()
                elif provider_choice == 2:
                    handle_french_stream()
                elif provider_choice == 3:
                    break  # Back to main menu

                input("\nPress Enter to continue...")
            continue

        if choice_idx == exit_idx:
            console.print("\n[cyan]👋 Goodbye![/cyan]\n")
            break


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        console.print("\n[yellow]⚠[/yellow] Exiting...\n")
        sys.exit(0)
