import threading
import socket
import json
import time
import urllib.parse
from flask import Flask, request, Response, stream_with_context
from curl_cffi import requests, CurlOpt
import m3u8

# Global Configuration
PROXY_PORT = 0
PROXY_HOST = "127.0.0.1"
PROXY_URL = None

app = Flask(__name__)

# Requested Google DNS Options
DNS_OPTIONS = {
    CurlOpt.DOH_URL: "https://8.8.8.8/dns-query",
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
    session = requests.Session(impersonate="chrome110")
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
    if not resp or resp.status_code != 200:
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

        # Rewrite segments
        for segment in m3u8_obj.segments:
            segment.uri = make_proxy_url("ts", segment.uri)

    # 4. Rebuild M3U8
    new_content = m3u8_obj.dumps()

    return Response(
        new_content,
        mimetype="application/vnd.apple.mpegurl",
        headers={"Access-Control-Allow-Origin": "*"},
    )


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
# Server Launch
# ---------------------------------------------------------------------------
def run_flask(port):
    # Disable verbose flask/werkzeug logs for performance
    import logging

    log = logging.getLogger("werkzeug")
    log.setLevel(logging.ERROR)

    app.run(host=PROXY_HOST, port=port, threaded=True, debug=False, use_reloader=False)


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
