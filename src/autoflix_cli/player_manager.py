import shutil
import platform
import os
import subprocess
import json
import urllib.parse
import time
import webbrowser
from rich.progress import Progress, SpinnerColumn, TextColumn
from .cli_utils import (
    select_from_list,
    print_info,
    print_error,
    print_success,
    print_warning,
    console,
)
from .scraping import player
from . import proxy
from typing import Dict, Any
from .tracker import tracker


DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64; rv:144.0) Gecko/20100101 Firefox/144.0"
)

# Launch modes: "proxy" streams through the local Flask proxy (curl_cffi,
# impersonated TLS, retry/buffering), "direct" hands the upstream URL and the
# headers over to the external player.
MODE_PROXY = "proxy"
MODE_DIRECT = "direct"
VALID_MODES = (MODE_PROXY, MODE_DIRECT)
DEFAULT_MODE = MODE_PROXY

# Modes each player code is able to use. A browser plays the URL inside a web
# player page served by the proxy, so it can never play the upstream URL
# directly: there would be no way to set the Referer header.
PLAYER_MODES: Dict[str, tuple] = {
    "mpv": (MODE_PROXY, MODE_DIRECT),
    "vlc": (MODE_PROXY, MODE_DIRECT),
    "browser": (MODE_PROXY,),
}

# Sec-Fetch-* values sent when an embed declares no explicit sec_headers:
# they emulate the iframe context the real web player would use.
DEFAULT_IFRAME_SEC_HEADERS = {
    "Sec-Fetch-Dest": "iframe",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "same-origin",
}

# Applied in direct mode so mpv recovers from dead segments / flaky CDNs
# instead of dying on the first error (ffmpeg protocol options).
# "reconnect" and "reconnect_at_eof" are deliberately left off: they make
# ffmpeg retry every clean end of stream and stall playback while logging
# "Will reconnect at N in X second(s), error=End of file".
DEFAULT_DIRECT_MPV_OPTIONS = (
    "--cache=yes",
    "--stream-lavf-o=reconnect_streamed=1,reconnect_on_network_error=1,"
    "reconnect_delay_max=4",
)


def _guess_subtitle_ext(url: str) -> str:
    """Guess a subtitle file extension from its URL (.ass/.vtt/.srt...)."""
    path = url.split("?")[0].lower()
    if path.endswith(".xz"):
        path = path[:-3]
    for ext in (".ass", ".srt", ".vtt", ".ssa", ".sub"):
        if path.endswith(ext):
            return ext
    return ".srt"


def _download_subtitles(subtitle_items) -> list:
    """
    Download subtitle file(s) to local temp files (handles .xz compression).

    Args:
        subtitle_items: List of dicts with a "url" key (or plain URL strings).
    Returns:
        List of local temp file paths.
    """
    from curl_cffi import requests
    import tempfile
    import lzma

    paths = []
    for item in subtitle_items:
        url = item["url"] if isinstance(item, dict) else item
        if not url or not isinstance(url, str) or not url.startswith("http"):
            continue
        try:
            headers = item.get("headers") if isinstance(item, dict) else None
            r = requests.get(url, timeout=15, impersonate="chrome", headers=headers)
            content = r.content
            ext = _guess_subtitle_ext(url)
            if url.lower().endswith(".xz"):
                content = lzma.decompress(content)
                ext = _guess_subtitle_ext(url[:-3])
            fd, temp_path = tempfile.mkstemp(suffix=ext, prefix="autoflix_sub_")
            with os.fdopen(fd, "wb") as f:
                f.write(content)
            paths.append(temp_path)
        except Exception as e:
            print_error(f"Failed to download subtitle: {e}")
    return paths


PLAYERS: Dict[str, Dict[str, str]] = {
    "mpv": {"display": "mpv"},
    "vlc": {"display": "vlc"},
    "browser": {"display": "browser"},
    "manual": {"display": "manual"},
}


def get_player_display(code: str, default: str = "manual") -> str:

    return PLAYERS.get(code, {}).get("display", default)


def get_all_players():

    return [(code, f"{player['display']}") for code, player in PLAYERS.items()]


def get_player_modes(player_code: str) -> tuple:
    """Return the launch modes supported by a player code."""
    return PLAYER_MODES.get(player_code, (MODE_PROXY,))


def resolve_launch_mode(player_config: dict, player_code: str) -> str:
    """
    Resolve how a player must open the stream: through the proxy or directly.

    Precedence: the per-player "modes" entry, then the legacy global "mode"
    key, then the default. Unknown or unsupported values fall back to the
    proxy, which is the mode known to work everywhere.

    Args:
        player_config: Configuration of the matched embed player
        player_code: Player code ("mpv", "vlc", "browser")

    Returns:
        MODE_PROXY or MODE_DIRECT
    """
    player_config = player_config or {}
    supported = get_player_modes(player_code)

    mode = None
    modes = player_config.get("modes")
    if isinstance(modes, dict):
        mode = modes.get(player_code)
    elif isinstance(modes, str):
        mode = modes
    if mode is None:
        mode = player_config.get("mode", DEFAULT_MODE)

    if not isinstance(mode, str) or mode not in VALID_MODES:
        if mode is not None:
            print_warning(
                f"Unknown launch mode '{mode}' for {player_code}, using '{DEFAULT_MODE}'."
            )
        return DEFAULT_MODE

    if mode not in supported:
        fallback = DEFAULT_MODE if DEFAULT_MODE in supported else supported[0]
        print_warning(
            f"{player_code} does not support '{mode}' mode, using '{fallback}'."
        )
        return fallback

    return mode


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


def _get_player_executable(player_code: str) -> str | None:
    """Locate a player executable (the browser player needs none)."""
    if player_code == "browser":
        return None
    if player_code == "vlc":
        return get_vlc_path()
    return shutil.which(player_code)


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


def _player_exit_hint(code: int) -> str:
    """Human hint for a failed player exit code (see mpv(1) EXIT CODES)."""
    return {
        2: "the file could not be played (link likely dead or expired)",
    }.get(code, "")


class _PlaybackAborted(Exception):
    """Playback failed in a way that must not offer a retry."""


def _match_player_config(url: str) -> tuple:
    """Find the embed configuration matching the player host of an URL."""
    return player.match_player_config(url)


def _compute_referer(
    url: str, headers: dict, player_config: dict, domain: str, is_direct: bool
) -> str:
    """Compute the Referer to use for the upstream request."""
    if is_direct:
        return headers.get("Referer", "")

    setting = (player_config or {}).get("referrer")
    if setting == "full":
        referer = url
    elif setting == "path":
        referer = f"https://{domain}/"
    elif isinstance(setting, str):
        referer = setting
    else:
        referer = f"https://{domain}/"

    return referer if referer.endswith("/") else f"{referer}/"


def _resolve_stream(url: str, headers: dict, is_direct: bool):
    """Resolve the playable stream URL and optional extracted subtitle URL."""
    if is_direct:
        return url, None

    try:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            progress.add_task(description="Getting stream URL...", total=None)
            stream_res = player.get_hls_link(url, headers, return_subs=True)
    except Exception as e:
        print_error(f"Error resolving stream URL: {e}")
        return None, None

    if isinstance(stream_res, tuple):
        stream_url, extracted_sub = stream_res
    else:
        stream_url, extracted_sub = stream_res, None

    if stream_url and stream_url.startswith("/"):
        stream_url = (
            "https://"
            + url.removeprefix("https://")
            .removeprefix("http://")
            .split("/")[0]
            + stream_url
        )

    if not stream_url:
        print_error("Could not resolve stream URL.")

    return stream_url, extracted_sub


def _build_upstream_headers(
    headers: dict, referer: str, player_config: dict, domain: str
) -> dict:
    """Headers forwarded to the proxy for the upstream request."""
    proxy_headers = headers.copy()
    if referer:
        proxy_headers["Referer"] = referer

    if player_config.get("alt-used") is True:
        proxy_headers["Alt-Used"] = domain

    sec_headers = player_config.get("sec_headers")
    if isinstance(sec_headers, str):
        for part in sec_headers.split(";"):
            if ":" in part:
                key, value = part.split(":", 1)
                proxy_headers[key.strip()] = value.strip()
    return proxy_headers


def _build_proxy_url(
    stream_url: str, proxy_headers: dict, player_config: dict, is_mp4: bool
) -> str | None:
    """Build the local proxy URL for a stream (None if the proxy is down)."""
    if not proxy.PROXY_URL:
        return None

    endpoint = "stream"
    if player_config.get("ext") == "mp4" or is_mp4:
        endpoint = "video"

    encoded_url = urllib.parse.quote(stream_url)
    encoded_headers = urllib.parse.quote(json.dumps(proxy_headers))
    return (
        f"{proxy.PROXY_URL}/{endpoint}?url={encoded_url}"
        f"&headers={encoded_headers}"
    )


def _origin_from_referer(referer: str) -> str:
    """Build an Origin header value (scheme://host[:port]) from a referer."""
    if not referer:
        return ""

    parsed = urllib.parse.urlparse(referer)
    if not parsed.scheme or not parsed.netloc:
        return ""

    return f"{parsed.scheme}://{parsed.netloc}"


def _build_direct_headers(
    headers: dict, referer: str, player_config: dict, domain: str
) -> str:
    """
    Build the mpv --http-header-fields value used for direct playback.

    mpv expects a comma separated list of "Field: value" pairs. Referer and
    User-Agent are left out because they have dedicated mpv options.
    """
    player_config = player_config or {}
    if player_config.get("no-header") is True:
        return ""

    direct_headers = _build_upstream_headers(headers, referer, player_config, domain)
    direct_headers.pop("Referer", None)
    direct_headers.pop("User-Agent", None)

    origin = _origin_from_referer(referer)
    if origin:
        direct_headers.setdefault("Origin", origin)

    sec_headers = player_config.get("sec_headers")
    if not isinstance(sec_headers, str) or not sec_headers.strip():
        direct_headers.update(DEFAULT_IFRAME_SEC_HEADERS)

    return ",".join(f"{key}: {value}" for key, value in direct_headers.items())


def _extra_player_options(player_config: dict) -> list:
    """Extra CLI options for direct playback ("mpv_options" in the config)."""
    extra = (player_config or {}).get("mpv_options") or []
    if isinstance(extra, str):
        extra = extra.split()
    return [str(option) for option in extra]


def _build_proxy_command(
    stream_url: str,
    headers: dict,
    player_config: dict,
    referer: str,
    domain: str,
    is_mp4: bool,
    player_code: str,
    player_executable: str,
    title: str,
    subtitle_paths: list,
) -> list | None:
    """Build the external player command line pointing at the local proxy."""
    proxy_headers = _build_upstream_headers(headers, referer, player_config, domain)
    local_stream_url = _build_proxy_url(
        stream_url, proxy_headers, player_config, is_mp4
    )
    if local_stream_url is None:
        return None

    cmd = [player_executable, local_stream_url]
    if player_code == "vlc":
        cmd.append(f"--meta-title={title}")
    else:
        cmd.append(f"--title={title}")

    for path in subtitle_paths:
        cmd.append(f"--sub-file={path}")

    return cmd


def _build_direct_command(
    stream_url: str,
    headers: dict,
    player_config: dict,
    referer: str,
    domain: str,
    player_code: str,
    player_executable: str,
    title: str,
    subtitle_paths: list,
) -> list:
    """Build the external player command line pointing at the upstream URL."""
    user_agent = headers.get("User-Agent", DEFAULT_USER_AGENT)

    cmd = [player_executable]
    if player_code == "vlc":
        cmd += [f":http-referrer={referer}", f":http-user-agent={user_agent}"]
        cmd.append(f"--meta-title={title}")
    else:
        cmd += [
            f"--referrer={referer}",
            f"--user-agent={user_agent}",
            f"--http-header-fields={_build_direct_headers(headers, referer, player_config, domain)}",
            f"--title={title}",
        ]
        cmd += list(DEFAULT_DIRECT_MPV_OPTIONS)
        cmd += _extra_player_options(player_config)

    for path in subtitle_paths:
        cmd.append(f"--sub-file={path}")

    cmd.append(stream_url)
    return cmd


def _build_browser_player_url(
    stream_url: str,
    headers: dict,
    player_config: dict,
    referer: str,
    domain: str,
    is_mp4: bool,
    subtitle_path: str | None,
) -> str | None:
    """Build the web player URL opened in the system browser."""
    proxy_headers = _build_upstream_headers(headers, referer, player_config, domain)
    local_stream_url = _build_proxy_url(
        stream_url, proxy_headers, player_config, is_mp4
    )
    if local_stream_url is None:
        return None

    browser_player_url = (
        f"{proxy.PROXY_URL}/player?url={urllib.parse.quote(local_stream_url)}"
    )
    if subtitle_path:
        browser_player_url += f"&sub_path={urllib.parse.quote(os.path.abspath(subtitle_path))}"

    return browser_player_url


def _play_in_browser(
    stream_url: str,
    headers: dict,
    player_config: dict,
    referer: str,
    domain: str,
    is_mp4: bool,
    subtitle_path: str | None,
) -> bool:
    """Open the stream in the system browser via the web player."""
    print_info("Launching [bold cyan]Browser[/bold cyan] Player...")

    browser_player_url = _build_browser_player_url(
        stream_url, headers, player_config, referer, domain, is_mp4, subtitle_path
    )
    if browser_player_url is None:
        print_error("Proxy server not initialized.")
        return False

    # Reset heartbeat and event
    proxy.player_finished_event.clear()
    proxy.player_heartbeat_time = time.time()

    webbrowser.open(browser_player_url)
    print_info(
        "Waiting for playback to finish in browser... (Close the tab to continue)"
    )

    try:
        # Polling loop
        while True:
            time.sleep(1)
            if proxy.player_finished_event.is_set():
                print_success(
                    "Playback finished (end of video or manually marked)."
                )
                return True

            # Check heartbeat timeout (e.g., > 6 seconds without heartbeat)
            if time.time() - proxy.player_heartbeat_time > 6.0:
                print_success("Browser tab closed or playback stopped.")
                return True
    except KeyboardInterrupt:
        print_info("\nPlayback interrupted by user.")
        return True
    except Exception as e:
        print_error(f"Error monitoring browser player: {e}")
        return False


def _play_via_proxy(
    stream_url: str,
    headers: dict,
    player_config: dict,
    referer: str,
    domain: str,
    is_mp4: bool,
    player_code: str,
    player_executable: str,
    title: str,
    subtitle_paths: list,
) -> bool:
    """Play the stream in an external player through the local proxy."""
    print_info(
        f"Launching [bold cyan]{player_code}[/bold cyan] via Proxy ({player_executable})..."
    )

    cmd = _build_proxy_command(
        stream_url,
        headers,
        player_config,
        referer,
        domain,
        is_mp4,
        player_code,
        player_executable,
        title,
        subtitle_paths,
    )
    if cmd is None:
        print_error("Proxy server not initialized.")
        return False

    if player_code == "vlc" and subtitle_paths:
        print_warning(
            "Note: VLC natively struggles to sync external subtitles on HLS/M3U8 streams (subtitles may flash). Strongly recommend using MPV instead."
        )

    try:
        subprocess.run(cmd, check=True)
        print_success("Playback completed successfully!")
        return True
    except subprocess.CalledProcessError as e:
        hint = _player_exit_hint(e.returncode)
        if hint:
            print_error(f"Error running player via proxy: {e} ({hint}).")
            raise _PlaybackAborted()
        print_error(f"Error running player via proxy: {e}")
    except Exception as e:
        print_error(f"Error running player via proxy: {e}")
    return False


def _play_direct(
    stream_url: str,
    headers: dict,
    player_config: dict,
    referer: str,
    domain: str,
    player_code: str,
    player_executable: str,
    title: str,
    subtitle_paths: list,
) -> bool:
    """Play the stream directly in an external player (no proxy)."""
    print_info(
        f"Launching [bold cyan]{player_code}[/bold cyan] directly ({player_executable})..."
    )

    cmd = _build_direct_command(
        stream_url,
        headers,
        player_config,
        referer,
        domain,
        player_code,
        player_executable,
        title,
        subtitle_paths,
    )
    if player_code == "mpv":
        print_info(f"Headers: {_build_direct_headers(headers, referer, player_config, domain)}")

    if player_code == "vlc" and subtitle_paths:
        print_warning(
            "Note: VLC natively struggles to sync external subtitles on HLS/M3U8 streams (subtitles may flash). Strongly recommend using MPV instead."
        )

    try:
        subprocess.run(cmd, check=True)
        print_success("Playback completed successfully!")
        return True
    except subprocess.CalledProcessError as e:
        hint = _player_exit_hint(e.returncode)
        if hint:
            print_error(f"Error running player: {e} ({hint}).")
            raise _PlaybackAborted()
        print_error(f"Error running player: {e}")
    except Exception as e:
        print_error(f"An unexpected error occurred: {e}")
    return False


def _launch_player(
    stream_url: str,
    headers: dict,
    player_config: dict,
    player_code: str,
    mode: str,
    is_mp4: bool,
    referer: str,
    domain: str,
    title: str,
    subtitle_paths: list,
    subtitle_path: str | None = None,
) -> bool:
    """Launch a player on a stream using the requested mode."""
    if player_code == "browser":
        return _play_in_browser(
            stream_url,
            headers,
            player_config,
            referer,
            domain,
            is_mp4,
            subtitle_path,
        )

    if mode == MODE_DIRECT:
        return _play_direct(
            stream_url,
            headers,
            player_config,
            referer,
            domain,
            player_code,
            _get_player_executable(player_code),
            title,
            subtitle_paths,
        )

    if mode == MODE_PROXY:
        if not proxy.PROXY_URL:
            print_error("Proxy server not initialized.")
            return False
        return _play_via_proxy(
            stream_url,
            headers,
            player_config,
            referer,
            domain,
            is_mp4,
            player_code,
            _get_player_executable(player_code),
            title,
            subtitle_paths,
        )

    print_error(f"Unknown launch mode: {mode}")
    return False


def _write_dev_debug_report(lines: list) -> str | None:
    """Save dev stream details to a file. Returns the path or None."""
    try:
        debug_dir = tracker.data_dir / "dev_debug"
        debug_dir.mkdir(parents=True, exist_ok=True)
        path = debug_dir / f"stream-{time.strftime('%Y%m%d-%H%M%S')}.txt"
        path.write_text("\n".join(lines), encoding="utf-8")
        return str(path)
    except OSError:
        return None


def _print_dev_stream_details(
    url: str,
    headers: dict,
    matched_player: str,
    player_config: dict,
    stream_url: str | None,
    extracted_sub: str | None,
) -> None:
    """Show resolved stream details in developer mode and save them."""
    extractor = (player_config or {}).get("type", "direct" if stream_url else "unknown")
    lines = [
        "[dev] embed URL: " + url,
        "[dev] headers: " + json.dumps(headers or {}),
        "[dev] matched player: " + (matched_player or "none"),
        "[dev] extractor type: " + str(extractor),
        "[dev] player config: " + json.dumps(player_config or {}),
        "[dev] stream URL: " + str(stream_url),
        "[dev] subtitle URL: " + str(extracted_sub),
    ]
    for line in lines:
        print_info(line)
    saved = _write_dev_debug_report(lines)
    if saved:
        print_info(f"[dev] details saved to: {saved}")


def play_video(
    url: str,
    headers: dict,
    title: str = "AutoFlix Stream",
    subtitle_url: str = None,
    subtitles: list = None,
    is_direct: bool = False,
    is_mp4: bool = False,
) -> bool:
    """
    Attempt to play a video with the chosen player.

    Args:
        url: Video player URL
        headers: HTTP headers for the request
        title: Title of the video to display in the player
        subtitle_url: Single primary subtitle URL (kept for compatibility)
        subtitles: Optional list of subtitle track dicts ({"url", "label", ...})
            so the user can pick the language inside the player
        is_direct: Whether the URL is a direct media file
        is_mp4: Whether the stream is an MP4

    Returns:
        True if playback succeeded, False otherwise
    """

    if hasattr(player, "new_url") and isinstance(player.new_url, dict):
        for old, new in player.new_url.items():
            url = url.replace(old, new)

    print_info(f"Resolving stream for: [cyan]{url}[/cyan]")

    subtitle_paths = []
    try:
        player_config, matched_player = _match_player_config(url)

        stream_url, extracted_sub = _resolve_stream(url, headers, is_direct)
        if tracker.get_developer_mode():
            _print_dev_stream_details(
                url, headers, matched_player, player_config, stream_url, extracted_sub
            )
        if extracted_sub and not subtitle_url:
            subtitle_url = extracted_sub

        if not stream_url:
            return False

        print_success(f"Stream URL: [cyan]{stream_url}[/cyan]")

        local_subtitle_path = subtitle_url
        subtitle_items = list(subtitles or [])
        if subtitle_url and subtitle_url.startswith("http"):
            subtitle_items.insert(0, subtitle_url)

        if subtitle_items:
            print_info("Downloading subtitle file(s) for compatibility...")
            subtitle_paths = _download_subtitles(subtitle_items)
            if subtitle_paths:
                local_subtitle_path = subtitle_paths[0]
                print_success(f"{len(subtitle_paths)} subtitle track(s) downloaded locally.")
            else:
                local_subtitle_path = None

        # Domain of the source page (used for Referer / Alt-Used headers).
        try:
            domain = url.split("/")[2].lower()
        except IndexError:
            domain = ""

        force_manual_mode = False
        while True:  # Loop to allow retrying with another player
            player_pref = tracker.get_player()
            if force_manual_mode or not player_pref or player_pref == "manual":
                players = ["mpv", "vlc", "browser", "← Back"]
                player_choice = select_from_list(players, "🎮 Select video player:")

                if players[player_choice] == "← Back":
                    return False

                player_name = players[player_choice]
            else:
                player_name = player_pref

            # Locate the player executable (the browser needs none).
            if player_name != "browser" and _get_player_executable(player_name) is None:
                if player_name == "vlc":
                    print_error("VLC not found. Please install it or add it to your PATH.")
                else:
                    print_error(f"{player_name} is not installed or not in PATH.")
                retry = handle_player_error(player_name)
                if retry == 1:  # Back
                    return False
                force_manual_mode = True
                continue

            # Calculate Referer
            referer = _compute_referer(
                url, headers, player_config, domain, is_direct
            )

            # Determine Launch Mode from config
            mode = resolve_launch_mode(player_config, player_name)

            try:
                result = _launch_player(
                    stream_url=stream_url,
                    headers=headers,
                    player_config=player_config,
                    player_code=player_name,
                    mode=mode,
                    is_mp4=is_mp4,
                    referer=referer,
                    domain=domain,
                    title=title,
                    subtitle_paths=subtitle_paths,
                    subtitle_path=local_subtitle_path,
                )
            except _PlaybackAborted:
                return False

            if result:
                return True

            # Playback failed: ask what to do next.
            retry = select_from_list(
                [
                    "Try another player",
                    "Retry with same player",
                    "← Back",
                ],
                "The player failed. What would you like to do?",
            )
            if retry == 2:  # Back
                force_manual_mode = True
                return False
            # Otherwise loop to try again.

    finally:
        # Clean up temp subtitle files downloaded for playback compatibility.
        for path in subtitle_paths:
            try:
                os.remove(path)
            except OSError:
                pass
