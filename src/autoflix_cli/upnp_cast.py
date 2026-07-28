"""
upnp_cast.py — UPnP/DLNA casting support for AutoFlix-CLI.

Handles:
  - LAN IP detection
  - SSDP discovery of DLNA MediaRenderer devices
  - Sending a stream URL to a renderer (SetAVTransportURI + Play)
  - Polling playback state (GetTransportInfo) to detect end of playback
"""

import socket
import time
import threading
from typing import Optional

from .cli_utils import print_info, print_error, print_success, print_warning

# ---------------------------------------------------------------------------
# LAN IP Detection
# ---------------------------------------------------------------------------

def get_lan_ip() -> str:
    """
    Detect the machine's LAN IP address (the one reachable from other devices
    on the same network). Falls back to 127.0.0.1 on failure.
    """
    try:
        # Connect to an external address (doesn't actually send data) to
        # find which local interface would be used for LAN traffic.
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"


# ---------------------------------------------------------------------------
# Device Discovery
# ---------------------------------------------------------------------------

def discover_renderers(timeout: float = 5.0) -> list:
    """
    Discover DLNA MediaRenderer devices on the local network via SSDP.

    Args:
        timeout: Seconds to wait for SSDP responses.

    Returns:
        List of upnpclient.Device objects that have an AVTransport service.
    """
    try:
        import upnpclient
    except ImportError:
        print_error("upnpclient is not installed. Run: uv pip install upnpclient")
        return []

    try:
        # upnpclient.discover() handles SSDP M-SEARCH internally
        all_devices = upnpclient.discover(timeout=timeout)
    except Exception as e:
        print_error(f"SSDP discovery failed: {e}")
        return []

    renderers = []
    for device in all_devices:
        # Only keep devices that expose AVTransport (i.e., can play media)
        if _get_av_transport(device) is not None:
            renderers.append(device)

    return renderers


def _get_av_transport(device):
    """Return the AVTransport service of a device, or None."""
    for service in device.services:
        if "AVTransport" in service.service_id or "AVTransport" in service.service_type:
            return service
    return None


# ---------------------------------------------------------------------------
# Casting
# ---------------------------------------------------------------------------

def cast_to_device(
    device,
    stream_url: str,
    title: str = "AutoFlix Stream",
    mime_type: str = "video/mp4",
) -> bool:
    """
    Send a stream URL to a DLNA renderer and start playback.

    Args:
        device: upnpclient Device object (must have AVTransport service).
        stream_url: Publicly reachable HTTP URL of the stream.
        title: Title to send as metadata (shown on TV UI).
        mime_type: MIME type hint for the renderer.

    Returns:
        True if playback was started successfully, False otherwise.
    """
    av_transport = _get_av_transport(device)
    if av_transport is None:
        print_error(f"Device '{device.friendly_name}' has no AVTransport service.")
        return False

    # Stop current playback if any (DLNA best practice)
    _try_stop(device)

    # Build DLNA DIDL-Lite metadata
    didl_metadata = _build_didl(title, stream_url, mime_type)


    success = False
    try:
        av_transport.SetAVTransportURI(
            InstanceID=0,
            CurrentURI=stream_url,
            CurrentURIMetaData=didl_metadata,
        )
        success = True
    except Exception as e:
        err_str = str(e)
        if "timed out" in err_str.lower() or "readtime" in err_str.lower():
            print_error(f"Failed to start playback on '{device.friendly_name}': {e}")
            from . import proxy as _proxy
            port = _proxy.PROXY_PORT or "PORT"
            print_warning(
                f"💡 [bold]Network/Firewall Tip:[/bold] The TV timed out trying to reach your PC.\n"
                f"On Fedora/Linux, firewalld may be blocking port {port}.\n"
                f"Try opening the port temporarily: [cyan]sudo firewall-cmd --add-port={port}/tcp --temporary[/cyan]"
            )
            return False

        # Retry with empty metadata if TV rejected rich DIDL XML
        print_warning(f"SetAVTransportURI with DIDL metadata failed ({e}). Retrying with basic metadata...")
        try:
            av_transport.SetAVTransportURI(
                InstanceID=0,
                CurrentURI=stream_url,
                CurrentURIMetaData="",
            )
            success = True
        except Exception as e2:
            print_error(f"Failed to start playback on '{device.friendly_name}': {e2}")
            return False

    if success:
        try:
            av_transport.Play(InstanceID=0, Speed="1")
            print_success(f"Casting to [bold cyan]{device.friendly_name}[/bold cyan]...")
            return True
        except Exception as e:
            err_str = str(e)
            # 704 = Format not supported — don't retry here, let caller try next MIME
            if "704" in err_str:
                raise  # Re-raise so interactive_upnp_cast can try next MIME type
            print_error(f"Failed to start Play on '{device.friendly_name}': {e}")
            return False

    return False


# MIME types to try in order for HLS→transcode on DLNA TVs
# Panasonic FZ800 accepts 'video/mpeg' for MPEG-TS but rejects 'video/mp2t'
_TRANSCODE_MIME_FALLBACK = [
    ("ts", "video/mpeg"),          # Panasonic & Samsung prefer this
    ("ts", "video/mp2t"),          # Standard DLNA MPEG-TS
    ("mp4", "video/mp4"),          # fMP4 fallback
]


def _build_didl(title: str, url: str, mime_type: str) -> str:
    """Build a minimal DIDL-Lite metadata XML string with DLNA flags."""
    safe_title = title.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    safe_url = url.replace("&", "&amp;")
    # Panasonic FZ800 and similar TVs need specific DLNA flags
    # DLNA.ORG_OP=01 = range + time-seek supported
    # DLNA.ORG_CI=0  = no transcoding info (we serve natively)
    # DLNA.ORG_FLAGS=0d500000... = streaming, limited operations
    dlna_flags = "DLNA.ORG_OP=01;DLNA.ORG_CI=0;DLNA.ORG_FLAGS=0d500000000000000000000000000000"
    return (
        '<DIDL-Lite xmlns="urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/" '
        'xmlns:upnp="urn:schemas-upnp-org:metadata-1-0/upnp/">'
        '<item id="0" parentID="-1" restricted="1">'
        f"<dc:title>{safe_title}</dc:title>"
        "<upnp:class>object.item.videoItem</upnp:class>"
        f'<res protocolInfo="http-get:*:{mime_type}:{dlna_flags}">{safe_url}</res>'
        "</item>"
        "</DIDL-Lite>"
    )


# ---------------------------------------------------------------------------
# Playback Monitoring
# ---------------------------------------------------------------------------

def wait_for_playback(
    device,
    poll_interval: float = 3.0,
    max_duration: float = 14400.0,  # 4h
) -> bool:
    """
    Poll the device's transport state until playback stops or is interrupted.

    Args:
        device: upnpclient Device object.
        poll_interval: Seconds between each poll.
        max_duration: Maximum seconds to wait before giving up.

    Returns:
        True when playback has ended, False on error or timeout.
    """
    av_transport = _get_av_transport(device)
    if av_transport is None:
        return False

    start_time = time.time()
    time.sleep(poll_interval)

    print_info(
        "⏳ Playback in progress on TV... "
        "[dim](Ctrl+C to stop monitoring)[/dim]"
    )

    try:
        while True:
            if time.time() - start_time > max_duration:
                print_warning("Maximum playback duration reached. Stopping monitor.")
                return True

            try:
                result = av_transport.GetTransportInfo(InstanceID=0)
                state = result.get("CurrentTransportState", "UNKNOWN")
            except Exception as e:
                print_error(f"Error polling transport state: {e}")
                time.sleep(poll_interval * 2)
                continue

            if state in ("STOPPED", "NO_MEDIA_PRESENT"):
                print_success("Playback finished on TV.")
                return True

            time.sleep(poll_interval)

    except KeyboardInterrupt:
        print_info("\nStopped monitoring playback.")
        _try_stop(device)
        return True

    return False


def _try_stop(device) -> None:
    """Attempt to send Stop command to the device (best-effort)."""
    try:
        av_transport = _get_av_transport(device)
        if av_transport:
            av_transport.Stop(InstanceID=0)
    except Exception:
        pass  # Not critical


# ---------------------------------------------------------------------------
# High-level helper used by player_manager
# ---------------------------------------------------------------------------

def _has_ffmpeg() -> bool:
    """Check whether ffmpeg is available on the system."""
    import shutil
    return shutil.which("ffmpeg") is not None


def _build_transcode_url(hls_proxy_url: str, lan_proxy_url: str, fmt: str = "mp4") -> str:
    """
    Build the /upnp-stream transcoding endpoint URL from an existing
    local HLS proxy URL.
    """
    import urllib.parse
    encoded = urllib.parse.quote(hls_proxy_url, safe="")
    return f"{lan_proxy_url}/upnp-stream?fmt={fmt}&url={encoded}"


def interactive_upnp_cast(
    stream_url: str,
    title: str = "AutoFlix Stream",
    is_hls: bool = True,
    lan_proxy_url: str = None,
) -> bool:
    """
    Full interactive flow:
      1. Discover renderers
      2. Let user select one
      3. Direct cast for MP4, or live MP4 stream transcode for HLS
      4. Monitor until end
    """
    from .cli_utils import select_from_list
    from rich.progress import Progress, SpinnerColumn, TextColumn
    from .cli_utils import console

    # Ensure lan_proxy_url is populated
    if not lan_proxy_url:
        from . import proxy as _proxy
        if _proxy.LAN_PROXY_URL:
            lan_proxy_url = _proxy.LAN_PROXY_URL
        else:
            lan_ip = get_lan_ip()
            port = _proxy.PROXY_PORT or 8080
            lan_proxy_url = f"http://{lan_ip}:{port}"

    # 1. Discover
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        progress.add_task(
            description="🔍 Scanning network for DLNA/UPnP devices...", total=None
        )
        renderers = discover_renderers(timeout=5.0)

    if not renderers:
        print_error(
            "No DLNA/UPnP renderer found on the network.\n"
            "Make sure your TV or media player is on and connected to the same Wi-Fi."
        )
        return False

    # 2. Select device
    device_names = [
        f"{d.friendly_name}  [dim]({d.location.split('/')[2]})[/dim]"
        for d in renderers
    ]
    device_names.append("← Back")

    choice = select_from_list(device_names, "📺 Select a DLNA device:")
    if choice == len(renderers):
        return False

    selected = renderers[choice]

    # 3. Handle playback based on stream type
    if not is_hls:
        # Direct MP4 stream: cast directly to TV as video/mp4
        print_info(f"Casting direct MP4 stream to [bold]{selected.friendly_name}[/bold]...")
        ok = cast_to_device(selected, stream_url, title=title, mime_type="video/mp4")
        if ok:
            wait_for_playback(selected)
            return True
        return False

    # HLS stream (.m3u8): transcode via ffmpeg, try MIME types in order
    if _has_ffmpeg():
        for fmt, mime in _TRANSCODE_MIME_FALLBACK:
            transcode_url = _build_transcode_url(stream_url, lan_proxy_url, fmt=fmt)
            print_info(
                f"🎥 Transcoding HLS → [{mime}] for TV compatibility..."
            )
            try:
                ok = cast_to_device(
                    selected,
                    transcode_url,
                    title=title,
                    mime_type=mime,
                )
            except Exception as e:
                if "704" in str(e):
                    print_warning(f"TV rejected {mime} (704), trying next format...")
                    continue
                print_error(f"Cast failed: {e}")
                return False

            if ok:
                wait_for_playback(selected)
                return True

            # cast_to_device returned False without raising → non-404 failure
            print_warning(f"Cast returned False for {mime}, trying next format...")

        print_error(
            "TV rejected all transcode formats (video/mpeg, video/mp2t, video/mp4).\n"
            "Your TV may not support HTTP streaming via DLNA."
        )
        return False

    # Fallback if ffmpeg is missing: try direct HLS cast
    print_warning("ffmpeg is not installed — attempting direct HLS cast...")
    ok = cast_to_device(
        selected, stream_url, title=title, mime_type="application/x-mpegURL"
    )
    if ok:
        wait_for_playback(selected)
        return True
    return False

