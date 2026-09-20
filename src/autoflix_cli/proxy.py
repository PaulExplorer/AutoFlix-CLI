import threading
import socket
import json
import time
import random
import select
import urllib.parse
import re
import m3u8
from flask import Flask, request, Response, stream_with_context
from curl_cffi import requests, CurlOpt

# Global Configuration
PROXY_PORT = 0
PROXY_HOST = "127.0.0.1"
PROXY_URL = None
_server_instance = None  # To store the server for shutdown

# Web Player State
player_finished_event = threading.Event()
player_heartbeat_time = 0

app = Flask(__name__)

# Requested Cloudflare DNS Options
DNS_OPTIONS = {
    CurlOpt.DOH_URL: "https://cloudflare-dns.com/dns-query",
    CurlOpt.DOH_SSL_VERIFYPEER: 0,
    CurlOpt.DOH_SSL_VERIFYHOST: 0,
}


def find_free_port():
    """Find a free port on localhost."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        return s.getsockname()[1]


def get_base_url(url):
    """Extracts the base URL to resolve relative paths."""
    return url.rsplit("/", 1)[0] + "/"


def make_proxy_url(endpoint, original_uri, base_uri, headers):
    """Build a proxy URL pointing back to this server for a given upstream URI."""
    absolute_url = urllib.parse.urljoin(base_uri, original_uri)
    encoded_url = urllib.parse.quote(absolute_url)
    encoded_headers = urllib.parse.quote(json.dumps(headers))
    return (
        f"http://{PROXY_HOST}:{PROXY_PORT}/{endpoint}?url={encoded_url}"
        f"&headers={encoded_headers}"
    )


# Statuses browsers / hls.js treat as transient and retry (fragment or playlist).
TRANSIENT_STATUS = {403, 404, 410, 429}


def _is_retryable_status(status):
    return status in TRANSIENT_STATUS or status >= 500


def _is_blocked_page(data, content_type=""):
    """True when the body looks like an anti-bot/challenge page (or is empty)."""
    ct = (content_type or "").lower()
    if "html" in ct:
        return True
    head = bytes(data)[:512].lstrip().lower()
    return not head or head.startswith((b"<html", b"<!doctype html", b"<script"))


def _client_gone_check(environ):
    """Return a predicate detecting that the client (mpv) closed this request.

    Werkzeug exposes the underlying connection in the WSGI environ. We only
    probe it with MSG_PEEK (no data consumed); a clean EOF means the player
    abandoned the transfer (seek/cancel/resize), so the upstream download can
    be stopped instead of being leaked into the void.
    """
    sock = None
    try:
        sock = environ.get("werkzeug.socket")
    except Exception:
        sock = None
    if sock is None:
        return lambda: False

    def is_gone():
        try:
            readable, _, _ = select.select([sock], [], [], 0)
            if not readable:
                return False
            return sock.recv(1, socket.MSG_PEEK) == b""
        except Exception:
            return False

    return is_gone


class _SegmentCancelled(Exception):
    """The player abandoned the request while a segment was being fetched."""


_session_cache = {}

def get_or_create_session(url, fresh=False):
    """Return the per-domain session (or a one-shot connection for retries).

    Headers travel per-request and are never mutated on the shared session, so
    concurrent segment/playlist downloads can no longer overwrite each other's
    headers or Referer. A ``fresh`` session opens a brand-new connection and
    inherits the base session cookies, mirroring how hls.js retries a fragment.
    """
    domain = urllib.parse.urlparse(url).netloc

    # Fresh sessions inherit the base session cookies so CDN auth
    # (Cloudflare, etc.) keeps working on the retry.
    cache_key = f"{domain}:fresh" if fresh else domain
    if fresh and domain not in _session_cache:
        get_or_create_session(url)

    if cache_key not in _session_cache:
        session = requests.Session(impersonate="chrome", allow_redirects="safe")
        session.curl_options.update(DNS_OPTIONS)
        # curl_cffi converts the per-request `timeout` into a low-speed abort
        # for streamed transfers (LOW_SPEED_LIMIT=1 over `timeout` seconds).
        # These session-level options are applied last (they override the
        # per-request ones), so a CDN that stalls briefly no longer kills the
        # segment at 15s. The 15s connect timeout is still enforced separately.
        session.curl_options.update(
            {
                CurlOpt.LOW_SPEED_TIME: 60,
                CurlOpt.LOW_SPEED_LIMIT: 1,
            }
        )
        if fresh:
            session.curl_options.update(
                {
                    CurlOpt.FRESH_CONNECT: 1,
                    CurlOpt.FORBID_REUSE: 1,
                }
            )
            base = _session_cache.get(domain)
            if base is not None:
                session.cookies.update(base.cookies)
        _session_cache[cache_key] = session

    return _session_cache[cache_key]


def fetch_with_retry(url, headers, method="GET", stream=False, max_retries=3):
    attempt = 0

    while attempt < max_retries:
        # First attempt reuses pooled connections; retries go through a fresh
        # session/connection (hls.js-style retry after a failed fetch).
        session = get_or_create_session(url, fresh=(attempt > 0))
        try:
            # Forward the Range header if present (for MP4 seeking)
            req_headers = dict(headers or {})
            if "Range" in request.headers:
                req_headers["Range"] = request.headers["Range"]

            response = session.request(
                method=method,
                url=url,
                headers=req_headers,
                stream=stream,
                timeout=15,  # Reasonable timeout
            )

            # Transient error (rate limit / 5xx / challenge) -> retry
            if _is_retryable_status(response.status_code):
                response.close()
                raise requests.RequestsError(f"Status {response.status_code}")

            return response

        except Exception as e:
            attempt += 1
            if attempt >= max_retries:
                print(
                    f"[ERROR] Failed to fetch {url} after {max_retries} attempts: {e}"
                )
                return None
            # Backoff with a little jitter: ~0.5s, then ~1s, etc.
            time.sleep(0.5 * attempt + random.uniform(0, 0.5))


def fetch_segment(url, headers, environ=None, client_range=None, max_retries=3):
    """Download a full segment/key/init body before serving it, with retries.

    Unlike fetch_with_retry this reads the whole body into memory (and verifies
    it) before anything is sent downstream, so a flaky CDN can no longer
    truncate a segment mid-transfer. Client Range requests (mpv byterange HLS,
    seeking) are forwarded and answered with the exact slice as a 206.
    retries mimic the fragment-retry behavior of browser players.

    Returns ``(data, status_code, extra_headers)`` or ``(None, None, {})``
    after ``max_retries``. Raises ``_SegmentCancelled`` when the client is
    detected gone, so the in-flight upstream transfer is not leaked.
    """
    is_cancelled = _client_gone_check(environ or {})
    attempt = 0

    while attempt < max_retries:
        response = None
        try:
            # First attempt reuses pooled connections; any retry goes through
            # a brand-new session/connection (browser-style segment retries).
            session = get_or_create_session(url, fresh=(attempt > 0))
            req_headers = dict(headers or {})
            req_headers.setdefault("Accept", "*/*")
            if client_range:
                req_headers["Range"] = client_range

            response = session.request(
                method="GET",
                url=url,
                headers=req_headers,
                stream=True,
                timeout=15,  # connect timeout; low-speed grace is 60s
            )

            status = response.status_code

            # Transient error (rate limit / 5xx / challenge) -> retry
            if _is_retryable_status(status):
                raise requests.RequestsError(f"Status {status}")

            data = bytearray()
            for chunk in response.iter_content():
                if is_cancelled():
                    raise _SegmentCancelled()
                data.extend(chunk)

            # A challenge/empty page back where a segment was expected is
            # treated as a failure and retried rather than served to the
            # player as a corrupt segment.
            if _is_blocked_page(
                bytes(data), response.headers.get("Content-Type") or ""
            ):
                raise requests.RequestsError("Blocked/empty body")

            # Defensive check for silent truncation (chunked response cut
            # early). Skipped when the body was content-encoded: curl
            # auto-decompresses, so Content-Length then reflects the
            # compressed size.
            content_length = response.headers.get("Content-Length")
            if (
                content_length
                and not response.headers.get("Content-Encoding")
                and len(data) != int(content_length)
            ):
                raise requests.RequestsError(
                    f"Truncated body: {len(data)}/{content_length} bytes"
                )

            # Preserve the range-slice metadata so the player gets a proper 206.
            extra = {}
            if status == 206 and client_range:
                for h in ("Content-Range", "Accept-Ranges"):
                    if response.headers.get(h):
                        extra[h] = response.headers[h]

            return bytes(data), status, extra

        except _SegmentCancelled:
            raise
        except Exception as e:
            attempt += 1
            if attempt >= max_retries:
                print(
                    f"[ERROR] Failed to fetch {url} after {max_retries} attempts: {e}"
                )
                return None, None, {}
            # Simple backoff with jitter: waits ~0.5s, then ~1s, etc.
            time.sleep(0.5 * attempt + random.uniform(0, 0.5))
        finally:
            if response is not None:
                try:
                    response.close()
                except Exception:
                    pass


# ---------------------------------------------------------------------------
# M3U8 rewriting (preserves the upstream bytes, only the URIs are proxied)
# ---------------------------------------------------------------------------
# Tags whose quoted URI="..." attribute designates another playlist (rewrite
# through /stream). Any other URI="..."-bearing tag (ext-IV keys, init
# segments, LL-HLS parts ...) is binary data fetched through /ts.
_PLAYLIST_URI_TAGS = {
    "EXT-X-MEDIA",
    "EXT-X-I-FRAME-STREAM-INF",
    "EXT-X-RENDITION-REPORT",
    "EXT-X-IMAGE-STREAM-INF",
}


def _rewrite_m3u8(content, target_url, headers, plain_endpoint):
    """Rewrite every URI of a playlist to go through this proxy.

    Works on the raw text instead of a parse/dump round-trip, so tags mpv and
    hls.js rely on (EXT-X-KEY / EXT-X-MAP / EXT-X-SESSION-KEY / EXT-X-MAP with
    BYTERANGE, LL-HLS preload hints ...) are never dropped or reformatted.
    `plain_endpoint` ("stream" or "ts") decides where bare segment/playlist URI
    lines go; it is derived structurally by the m3u8 parser in /stream.
    """
    base_uri = get_base_url(target_url)
    proxied_prefix = f"http://{PROXY_HOST}:{PROXY_PORT}/"

    def proxify(endpoint, uri):
        if not uri or uri.startswith(proxied_prefix):
            return uri
        return make_proxy_url(endpoint, uri, base_uri, headers)

    def rewrite_body(body):
        text = body
        stripped = text.strip()
        if not stripped:
            return body

        if stripped.startswith("#"):
            # Attribute-based URI: KEY/MAP/MEDIA/I-FRAME-STREAM-INF/...
            if 'URI="' not in text:
                return body
            endpoint = (
                "stream"
                if any(
                    stripped.startswith(f"#{t}:") for t in _PLAYLIST_URI_TAGS
                )
                else "ts"
            )
            return re.sub(
                r'URI="([^"]*)"',
                lambda m: f'URI="{proxify(endpoint, m.group(1))}"',
                text,
            )

        # Plain URI line: a segment (media playlist) or a variant playlist
        # (master playlist).
        return proxify(plain_endpoint, stripped)

    # Rebuild, keeping the original newlines.
    return "".join(
        rewrite_body(line.rstrip("\r\n")) + line[len(line.rstrip("\r\n")):]
        for line in content.splitlines(keepends=True)
    )


# ---------------------------------------------------------------------------
# Route: /stream (For .m3u8 files)
# ---------------------------------------------------------------------------
@app.route("/stream")
def proxy_stream():
    target_url = request.args.get("url")
    headers_str = request.args.get("headers", "{}")

    if not target_url:
        return "Missing URL parameter", 400

    try:
        headers = json.loads(headers_str)
    except:
        headers = {}

    # 1. Fetch original M3U8 content
    resp = fetch_with_retry(target_url, headers)
    if not resp or resp.status_code not in [200, 206]:
        return "Error fetching upstream m3u8", 502

    content = resp.text

    # 2. Rewrite the playlist URIs to point back at this proxy while keeping
    #    the upstream bytes exactly as served (tags mpv cares about are never
    #    dropped or reformatted by a parse/dump round-trip).
    if "#EXTM3U" in content:
        # The m3u8 parser (lenient) is used as a structural detector only: it
        # knows whether this is a master/variant doc or a media playlist, which
        # decides where bare playlist/segment URI lines must be routed. The
        # actual rewriting stays byte-faithful (regex).
        try:
            parsed = m3u8.loads(content, uri=target_url)
        except Exception:
            parsed = None
        plain_endpoint = (
            "stream"
            if parsed
            and (
                parsed.playlists
                or parsed.is_variant
                or parsed.iframe_playlists
                or parsed.image_playlists
            )
            else "ts"
        )
        new_content = _rewrite_m3u8(content, target_url, headers, plain_endpoint)
    else:
        new_content = content

    return Response(
        new_content,
        mimetype="application/vnd.apple.mpegurl",
        headers={"Access-Control-Allow-Origin": "*"},
    )


# ---------------------------------------------------------------------------
# Catch-all for debugging 404s
# ---------------------------------------------------------------------------
@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def catch_all(path):
    print(f"[PROXY 404 HIT] Invalid path requested: {path}")
    return f"Not Found: {path}", 404


# ---------------------------------------------------------------------------
# Route: /ts (For video segments and keys)
# ---------------------------------------------------------------------------
@app.route("/ts")
def proxy_ts():
    target_url = request.args.get("url")
    headers_str = request.args.get("headers", "{}")

    if not target_url:
        return "Missing URL", 400

    try:
        headers = json.loads(headers_str)
    except:
        headers = {}

    # mpv issues Range requests for byterange-based HLS (EXT-X-BYTERANGE, some
    # fMP4 init segments). Forward them so the exact slice is fetched and
    # served, instead of returning the whole file (misaligned => corruption).
    client_range = request.headers.get("Range")

    try:
        data, status, extra_headers = fetch_segment(
            target_url, headers, request.environ, client_range=client_range
        )
    except _SegmentCancelled:
        # The player abandoned this transfer; nothing to serve anymore.
        return "Cancelled", 499

    if data is None:
        return "Error fetching segment", 502

    # Force Content-Type so VLC doesn't bug if the server sends .html
    # video/mp2t is the standard for TS segments. An exact Content-Length
    # gives players a clean segment boundary (no "corrupt packet" tails).
    response_headers = {
        "Content-Type": "video/mp2t",
        "Access-Control-Allow-Origin": "*",
        "Content-Length": str(len(data)),
    }
    response_headers.update(extra_headers)

    return Response(data, status=status, headers=response_headers)


# ---------------------------------------------------------------------------
# Route: /video (For single MP4 files with Seeking)
# ---------------------------------------------------------------------------
@app.route("/video")
def proxy_video():
    target_url = request.args.get("url")
    headers_str = request.args.get("headers", "{}")

    if not target_url:
        return "Missing URL", 400

    try:
        headers = json.loads(headers_str)
    except:
        headers = {}

    # Fetch stream
    resp = fetch_with_retry(target_url, headers, stream=True)
    if not resp:
        return "Error fetching video", 502

    # Handle response headers for seeking
    excluded_headers = [
        "content-encoding",
        "content-length",
        "transfer-encoding",
        "connection",
    ]
    response_headers = [
        (k, v) for k, v in resp.headers.items() if k.lower() not in excluded_headers
    ]

    # Forward Content-Length if available so VLC knows duration/size
    if "Content-Length" in resp.headers:
        response_headers.append(("Content-Length", resp.headers["Content-Length"]))

    # Support for Range Request (Partial Content 206)
    status_code = resp.status_code

    def generate():
        try:
            for chunk in resp.iter_content(
                chunk_size=16384
            ):  # Slightly larger chunks for MP4
                if chunk:
                    yield chunk
        finally:
            # Stop pulling upstream as soon as the client disconnects (seek).
            try:
                resp.close()
            except Exception:
                pass

    return Response(
        stream_with_context(generate()), status=status_code, headers=response_headers
    )


# ---------------------------------------------------------------------------
# Routes: Web Player & Heartbeat
# ---------------------------------------------------------------------------
@app.route("/player")
def proxy_player_ui():
    html_content = """<!DOCTYPE html>
<html>
<head>
    <title>AutoFlix Web Player</title>
    <meta charset="utf-8">
    <link rel="stylesheet" href="https://cdn.plyr.io/3.7.8/plyr.css" />
    <style>
        body, html { margin: 0; padding: 0; width: 100%; height: 100%; background-color: #000; overflow: hidden; font-family: sans-serif; }
        .plyr { width: 100%; height: 100%; }
        #controls-overlay { position: absolute; top: 20px; right: 20px; z-index: 1000; opacity: 0; transition: opacity 0.3s; }
        body:hover #controls-overlay, .plyr--active #controls-overlay { opacity: 1; }
        .action-btn { background-color: rgba(255, 0, 0, 0.7); color: white; border: none; padding: 10px 15px; border-radius: 5px; cursor: pointer; font-size: 16px; font-weight: bold; }
        .action-btn:hover { background-color: rgba(255, 0, 0, 1); }
        .message { position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%); color: white; font-size: 24px; display: none; text-align: center; z-index: 2000; }
        .message button { margin-top: 20px; padding: 10px 20px; font-size: 18px; cursor: pointer; }
    </style>
    <script src="https://cdn.jsdelivr.net/npm/hls.js@latest"></script>
    <script src="https://cdn.plyr.io/3.7.8/plyr.js"></script>
</head>
<body>
    <div id="controls-overlay">
        <button id="closeBtn" class="action-btn">Mark as watched & Close</button>
    </div>
    
    <video id="video" controls crossorigin="anonymous" playsinline>
        <!-- Title and captions will be injected via JS -->
    </video>
    
    <div id="finishedMsg" class="message">
        Video finished! You can safely close this tab.<br>
        <button onclick="window.close()">Close Tab</button>
    </div>

    <script>
        document.addEventListener("DOMContentLoaded", () => {
            const video = document.getElementById('video');
            const urlParams = new URLSearchParams(window.location.search);
            const source = urlParams.get('url');
            const subPath = urlParams.get('sub_path');
            
            const isMp4 = source && source.indexOf('/video') !== -1;
            const closeBtn = document.getElementById('closeBtn');

            // Setup subtitle track if provided
            if (subPath) {
                const track = document.createElement('track');
                track.kind = 'captions';
                track.label = 'Subtitles';
                track.src = '/player/subtitle?path=' + encodeURIComponent(subPath);
                track.default = true;
                video.appendChild(track);
            }

            const defaultOptions = {
                captions: { active: true, update: true, language: 'auto' },
                controls: [
                    'play-large', 'play', 'progress', 'current-time', 'mute', 'volume',
                    'captions', 'settings', 'pip', 'airplay', 'fullscreen'
                ],
                settings: ['captions', 'quality', 'speed']
            };

            let player;

            if (source) {
                if (isMp4 || !Hls.isSupported()) {
                    // Native playback for MP4 or native HLS (Safari)
                    video.src = source;
                    player = new Plyr(video, defaultOptions);
                    player.play();
                } else {
                    // hls.js for M3U8 with quality selection
                    const hls = new Hls({
                        xhrSetup: function(xhr, url) {
                            xhr.withCredentials = false; // Important to avoid CORS issues if not needed
                        }
                    });
                    
                    hls.loadSource(source);
                    hls.attachMedia(video);
                    
                    hls.on(Hls.Events.MANIFEST_PARSED, function (event, data) {
                        // Extract available qualities
                        const availableQualities = hls.levels.map((l) => l.height);
                        // Add Auto option
                        availableQualities.unshift(0); 

                        defaultOptions.quality = {
                            default: 0, // 0 means auto
                            options: availableQualities,
                            forced: true,
                            onChange: (e) => updateQuality(e),
                        };
                        // Custom labels for the qualities
                        defaultOptions.i18n = {
                            qualityLabel: {
                                0: 'Auto',
                            },
                        };

                        player = new Plyr(video, defaultOptions);
                        
                        // Play immediately after setup
                        player.play();
                    });

                    // Recover from errors
                    hls.on(Hls.Events.ERROR, function(event, data) {
                        if (data.fatal) {
                            switch (data.type) {
                                case Hls.ErrorTypes.NETWORK_ERROR:
                                    console.error("Fatal network error encountered, try to recover");
                                    hls.startLoad();
                                    break;
                                case Hls.ErrorTypes.MEDIA_ERROR:
                                    console.error("Fatal media error encountered, try to recover");
                                    hls.recoverMediaError();
                                    break;
                                default:
                                    hls.destroy();
                                    break;
                            }
                        }
                    });

                    function updateQuality(newQuality) {
                        if (newQuality === 0) {
                            window.hls.currentLevel = -1; // -1 triggers auto level
                        } else {
                            // Find the index of the level matching the requested height
                            const levelIndex = hls.levels.findIndex((l) => l.height === newQuality);
                            if (levelIndex !== -1) {
                                hls.currentLevel = levelIndex;
                            }
                        }
                    }
                    window.hls = hls; // Make available globally for quality update
                }
            }

            // Heartbeat logic
            let heartbeatInterval = setInterval(() => {
                fetch('/player/heartbeat').catch(e => console.log('Heartbeat failed'));
            }, 2000);

            function endPlayback() {
                clearInterval(heartbeatInterval);
                fetch('/player/end').then(() => {
                    document.getElementById('finishedMsg').style.display = 'block';
                    document.getElementById('controls-overlay').style.display = 'none';
                    if(player) {
                        player.destroy();
                    } else {
                        video.style.display = 'none';
                    }
                    // Try to close tab automatically
                    setTimeout(() => window.close(), 1000);
                }).catch(e => {
                    // Fallback UI
                    document.getElementById('finishedMsg').style.display = 'block';
                    if(player) {
                        player.destroy();
                    } else {
                        video.style.display = 'none';
                    }
                });
            }

            // Listen to video native 'ended' event
            video.addEventListener('ended', endPlayback);
            closeBtn.addEventListener('click', endPlayback);
        });
    </script>
</body>
</html>"""
    return Response(html_content, mimetype="text/html")


@app.route("/player/subtitle")
def proxy_player_subtitle():
    import os

    sub_path = request.args.get("path")
    if not sub_path or not os.path.exists(sub_path):
        return "Subtitle not found", 404

    try:
        with open(sub_path, "rb") as f:
            content = f.read()

        # Standardize SRT to WebVTT for HTML5 video <track> compatibility
        if sub_path.lower().endswith(".srt"):
            text = content.decode("utf-8", errors="ignore")
            # Replace timestamps ',' with '.' for VTT format e.g: 00:00:10,500 -> 00:00:10.500
            import re

            vtt_content = "WEBVTT\n\n" + re.sub(
                r"(\d{2}:\d{2}:\d{2}),(\d{3})", r"\1.\2", text
            )
            return Response(
                vtt_content,
                mimetype="text/vtt",
                headers={"Access-Control-Allow-Origin": "*"},
            )

        return Response(
            content, mimetype="text/vtt", headers={"Access-Control-Allow-Origin": "*"}
        )
    except Exception as e:
        return f"Error loading subtitle: {e}", 500


@app.route("/player/heartbeat")
def proxy_player_heartbeat():
    global player_heartbeat_time
    # Update global timestamp of the heartbeat
    player_heartbeat_time = time.time()
    return "ok", 200


@app.route("/player/end")
def proxy_player_end():
    global player_finished_event
    player_finished_event.set()
    return "ok", 200


# ---------------------------------------------------------------------------
# Server Launch
# ---------------------------------------------------------------------------
def run_flask(port):
    global _server_instance
    # Disable verbose flask/werkzeug logs for performance
    import logging
    from werkzeug.serving import make_server

    log = logging.getLogger("werkzeug")
    log.setLevel(logging.ERROR)

    _server_instance = make_server(PROXY_HOST, port, app, threaded=True)
    _server_instance.serve_forever()


def start_proxy_server(port=0):
    global PROXY_PORT, PROXY_URL

    if port == 0:
        port = find_free_port()

    PROXY_PORT = port
    PROXY_URL = f"http://{PROXY_HOST}:{PROXY_PORT}"

    # Launch in a Daemon thread (stops when the main program stops)
    t = threading.Thread(target=run_flask, args=(port,))
    t.daemon = True
    t.start()

    print(f"[*] M3U8 Proxy started on http://{PROXY_HOST}:{PROXY_PORT}")
    return port


def stop_proxy_server():
    """Shuts down the proxy server gracefully."""
    global _server_instance
    if _server_instance:
        _server_instance.shutdown()
        _server_instance = None


# ---------------------------------------------------------------------------
# Usage Example (if run directly)
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # Start the proxy
    my_port = start_proxy_server(0)

    # This simulates your main application
    print("Main application running... Press Ctrl+C to quit.")

    # Example URL for VLC (only works with a real source URL)
    # url_source = "https://example.com/master.m3u8"
    # headers_source = {"User-Agent": "Mozilla/5.0 ...", "Referer": "https://example.com"}
    # encoded_url = urllib.parse.quote(url_source)
    # encoded_headers = urllib.parse.quote(json.dumps(headers_source))
    # print(f"Link for VLC: http://127.0.0.1:{my_port}/stream?url={encoded_url}&headers={encoded_headers}")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("Stopping.")
