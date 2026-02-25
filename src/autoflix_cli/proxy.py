import threading
import socket
import json
import time
import urllib.parse
import re
from flask import Flask, request, Response, stream_with_context
from curl_cffi import requests, CurlOpt
import m3u8

# Global Configuration
PROXY_PORT = 0
PROXY_HOST = "127.0.0.1"
PROXY_URL = None
_server_instance = None  # To store the server for shutdown

# Web Player State
player_finished_event = threading.Event()
player_heartbeat_time = 0

app = Flask(__name__)

# Requested Google DNS Options
DNS_OPTIONS = {
    CurlOpt.DOH_URL: "https://1.1.1.1/dns-query",
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


def create_session(headers_dict=None):
    """Creates a curl_cffi session optimized for anonymity."""
    session = requests.Session(impersonate="chrome")
    # Apply specific DNS options
    session.curl_options.update(DNS_OPTIONS)

    if headers_dict:
        session.headers.update(headers_dict)

    return session


def fetch_with_retry(url, headers, method="GET", stream=False, max_retries=3):
    """
    Performs a request with an automatic retry system.
    Handles timeouts and network errors to avoid breaking the stream.
    """
    attempt = 0
    session = create_session(headers)

    while attempt < max_retries:
        try:
            # Forward the Range header if present (for MP4 seeking)
            req_headers = headers.copy() if headers else {}

            # Handle the Range header coming from the client (VLC)
            if "Range" in request.headers:
                req_headers["Range"] = request.headers["Range"]

            response = session.request(
                method=method,
                url=url,
                headers=req_headers,
                stream=stream,
                timeout=15,  # Reasonable timeout
            )

            # If 429 error (Rate Limit) or 5xx, retry
            if response.status_code == 429 or response.status_code >= 500:
                raise requests.RequestsError(f"Status {response.status_code}")

            return response

        except Exception as e:
            attempt += 1
            # Simple backoff: waits 0.5s, then 1s, etc.
            time.sleep(0.5 * attempt)
            if attempt >= max_retries:
                print(
                    f"[ERROR] Failed to fetch {url} after {max_retries} attempts: {e}"
                )
                return None


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
    base_uri = get_base_url(target_url)

    # 2. Parsing with m3u8 library
    try:
        m3u8_obj = m3u8.loads(content, uri=target_url)
    except Exception as e:
        # If parsing fails, return as is (fallback)
        return Response(content, mimetype="application/vnd.apple.mpegurl")

    # Helper function to build the proxy URL to our routes
    def make_proxy_url(endpoint, original_uri):
        # Absolute URL resolution if relative
        absolute_url = urllib.parse.urljoin(base_uri, original_uri)
        encoded_url = urllib.parse.quote(absolute_url)
        encoded_headers = urllib.parse.quote(json.dumps(headers))
        # Points to localhost:PORT
        return f"http://{PROXY_HOST}:{PROXY_PORT}/{endpoint}?url={encoded_url}&headers={encoded_headers}"

    # 3. Rewriting segments (.ts)
    # We directly modify the m3u8 object or perform string replace if the object is too complex.
    # The most reliable approach is often rewriting the text, but m3u8 obj allows managing keys.

    # If it's a Master Playlist (contains other playlists)
    if m3u8_obj.playlists:
        for p in m3u8_obj.playlists:
            p.uri = make_proxy_url("stream", p.uri)

        # Handle Media (Alternative Audio/Subtitles)
        for m in m3u8_obj.media:
            if m.uri:
                m.uri = make_proxy_url("stream", m.uri)

    # If it's a Media Playlist (contains segments)
    else:
        # Rewrite encryption keys (AES-128 etc)
        # CRUCIAL: keys must pass through the proxy otherwise 403/CORS
        for key in m3u8_obj.keys:
            if key and key.uri:
                key.uri = make_proxy_url(
                    "ts", key.uri
                )  # Using /ts to fetch the key (it's just a binary)

        # Rewrite initialization segment (for fMP4 HLS)
        # We also use a regex fallback at the end because m3u8 library sometimes fails to dump the changes to segment_map
        if hasattr(m3u8_obj, "segment_map"):
            for seg_map in m3u8_obj.segment_map:
                if seg_map and seg_map.uri:
                    seg_map.uri = make_proxy_url("ts", seg_map.uri)

        # Rewrite segments
        for segment in m3u8_obj.segments:
            segment.uri = make_proxy_url("ts", segment.uri)

    # 4. Rebuild M3U8
    new_content = m3u8_obj.dumps()

    # Regex Fallback for EXT-X-MAP if m3u8 library didn't update the text
    def replace_map_uri(match):
        original_uri = match.group(1)
        # If already proxied (by the object manipulation), skip
        if str(PROXY_PORT) in original_uri and "/ts?url=" in original_uri:
            return match.group(0)

        # It's an un-proxied URI provided by dumps()
        new_uri = make_proxy_url("ts", original_uri)
        return f'#EXT-X-MAP:URI="{new_uri}"'

    new_content = re.sub(r'#EXT-X-MAP:URI="([^"]+)"', replace_map_uri, new_content)

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

    # Fetch in stream mode
    resp = fetch_with_retry(target_url, headers, stream=True)
    if not resp:
        return "Error fetching segment", 502

    # Force Content-Type so VLC doesn't bug if the server sends .html
    # video/mp2t is the standard for TS segments
    response_headers = {
        "Content-Type": "video/mp2t",
        "Access-Control-Allow-Origin": "*",
    }

    # Use stream_with_context to return chunks as they come
    # This is where memory efficiency happens
    def generate():
        for chunk in resp.iter_content(chunk_size=8192):
            if chunk:
                yield chunk

    return Response(
        stream_with_context(generate()),
        status=resp.status_code,
        headers=response_headers,
    )


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
        for chunk in resp.iter_content(
            chunk_size=16384
        ):  # Slightly larger chunks for MP4
            if chunk:
                yield chunk

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
