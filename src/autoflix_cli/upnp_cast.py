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

    # Build minimal DIDL-Lite metadata (required by many renderers)
    didl_metadata = _build_didl(title, stream_url, mime_type)

    try:
        # 1. Set the URI
        av_transport.SetAVTransportURI(
            InstanceID=0,
            CurrentURI=stream_url,
            CurrentURIMetaData=didl_metadata,
        )

        # 2. Start playback
        av_transport.Play(InstanceID=0, Speed="1")

        print_success(f"Casting to [bold cyan]{device.friendly_name}[/bold cyan]...")
        return True

    except Exception as e:
        print_error(f"Failed to start playback on '{device.friendly_name}': {e}")
        return False


def _build_didl(title: str, url: str, mime_type: str) -> str:
    """Build a minimal DIDL-Lite metadata XML string."""
    safe_title = title.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    safe_url = url.replace("&", "&amp;")
    return (
        '<DIDL-Lite xmlns="urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/" '
        'xmlns:upnp="urn:schemas-upnp-org:metadata-1-0/upnp/">'
        '<item id="1" parentID="0" restricted="1">'
        f"<dc:title>{safe_title}</dc:title>"
        "<upnp:class>object.item.videoItem</upnp:class>"
        f'<res protocolInfo="http-get:*:{mime_type}:*">{safe_url}</res>'
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
    # Give the renderer a moment to start playing before we poll
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
                # Don't abort immediately — transient errors happen on some TVs
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

def interactive_upnp_cast(
    stream_url: str,
    title: str = "AutoFlix Stream",
    is_hls: bool = True,
) -> bool:
    """
    Full interactive flow:
      1. Discover renderers
      2. Let user select one
      3. Cast + monitor

    Args:
        stream_url: Local proxy URL (using LAN IP, reachable from TV).
        title: Video title.
        is_hls: True for M3U8/HLS streams, False for direct MP4.

    Returns:
        True if playback succeeded, False otherwise.
    """
    from .cli_utils import select_from_list
    from rich.progress import Progress, SpinnerColumn, TextColumn
    from .cli_utils import console

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

    # 3. Determine MIME type hint
    mime_type = "application/x-mpegURL" if is_hls else "video/mp4"

    # 4. Cast
    ok = cast_to_device(selected, stream_url, title=title, mime_type=mime_type)
    if not ok:
        return False

    # 5. Monitor until end
    wait_for_playback(selected)
    return True
