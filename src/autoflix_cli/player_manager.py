import shutil
import platform
import os
import subprocess
import json
import urllib.parse
from rich.progress import Progress, SpinnerColumn, TextColumn
from .cli_utils import (
    select_from_list,
    print_info,
    print_error,
    print_success,
    console,
)
from .scraping import player
from . import proxy


DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64; rv:144.0) Gecko/20100101 Firefox/144.0"
)


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


def play_video(
    url: str,
    headers: dict,
    title: str = "AutoFlix Stream",
    subtitle_url: str = None,
    is_direct: bool = False,
) -> bool:
    """
    Attempt to play a video with the chosen player.

    Args:
        url: Video player URL
        headers: HTTP headers for the request
        title: Title of the video to display in the player

    Returns:
        True if playback succeeded, False otherwise
    """

    if hasattr(player, "new_url") and isinstance(player.new_url, dict):
        for old, new in player.new_url.items():
            url = url.replace(old, new)

    print_info(f"Resolving stream for: [cyan]{url}[/cyan]")

    # Determine player configuration
    player_config = {}
    for player_name, config in player.players.items():
        if player_name in url.lower():
            player_config = config
            break

    if is_direct:
        stream_url = url
    else:
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
                        + url.removeprefix("https://")
                        .removeprefix("http://")
                        .split("/")[0]
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

        user_agent = headers.get("User-Agent", DEFAULT_USER_AGENT)

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
                if isinstance(sec_headers, str):
                    for part in sec_headers.split(";"):
                        if ":" in part:
                            k, v = part.split(":", 1)
                            proxy_headers[k.strip()] = v.strip()

            headers_json = json.dumps(proxy_headers)
            encoded_url = urllib.parse.quote(stream_url)
            encoded_headers = urllib.parse.quote(headers_json)

            if not proxy.PROXY_URL:
                print_error("Proxy server not initialized.")
                return False

            endpoint = "stream"
            if "ext" in player_config and player_config["ext"] == "mp4":
                endpoint = "video"

            local_stream_url = f"{proxy.PROXY_URL}/{endpoint}?url={encoded_url}&headers={encoded_headers}"

            try:
                cmd = [player_executable, local_stream_url]
                if player_name == "vlc":
                    cmd.append(f"--meta-title={title}")
                    if subtitle_url:
                        cmd.append(f"--sub-file={subtitle_url}")
                elif player_name == "mpv":
                    cmd.append(f"--title={title}")
                    if subtitle_url:
                        cmd.append(f"--sub-files={subtitle_url}")

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
                    if subtitle_url:
                        cmd.append(f"--sub-file={subtitle_url}")
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
                    ]
                    if subtitle_url:
                        cmd.append(f"--sub-files={subtitle_url}")
                    cmd.append(stream_url)
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


def select_and_play_player(
    supported_players: list, referer: str, title: str, subtitle_url: str = None
) -> bool:
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
            subtitle_url=subtitle_url,
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
