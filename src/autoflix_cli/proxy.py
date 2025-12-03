import threading
import urllib.parse
import json
import re
import time
from flask import Flask, Response, request, stream_with_context
import logging

from curl_cffi import requests as cffi_requests
from curl_cffi.const import CurlOpt

curl_options = {
    # Google DNS to bypass potential ISP blocks
    CurlOpt.DOH_URL: "https://8.8.8.8/dns-query",
    # Disable SSL verification for the DNS query itself
    CurlOpt.DOH_SSL_VERIFYPEER: 0,
    CurlOpt.DOH_SSL_VERIFYHOST: 0,
}

app = Flask(__name__)

# Global variables to store current stream configuration
current_config = {"url": None, "headers": {}}


def get_base_url(url):
    """Get the base URL to resolve relative paths in the m3u8."""
    parsed = urllib.parse.urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}{'/'.join(parsed.path.split('/')[:-1])}/"


def requests_retry_session(url, headers, retries=3, backoff_factor=0.5):
    """
    Wraps the request with retry logic and forces connection close.
    """
    req_headers = headers.copy()

    # CRITICAL: Tells the server to close the socket after the request.
    # Prevents "Connection reset by peer" errors on long streams.
    # req_headers["Connection"] = "close"

    for i in range(retries):
        try:
            response = cffi_requests.get(
                url,
                headers=req_headers,
                impersonate="chrome120",
                timeout=45,
                curl_options=curl_options,
                stream=True,
            )

            # If server error (5xx) or Rate Limit (429), retry
            if response.status_code in [500, 502, 503, 504, 429]:
                response.close()
                raise Exception(f"Status code {response.status_code}")

            return response

        except Exception as e:
            # If last attempt, raise the error
            if i == retries - 1:
                print(f"Failed after {retries} attempts: {e}")
                raise e
            time.sleep(backoff_factor * (i + 1))


def safe_iter_content(response):
    """
    Generator that handles 'GeneratorExit' when VLC disconnects/seeks.
    """
    try:
        iterator = response.iter_content()
        for chunk in iterator:
            yield chunk
    except GeneratorExit:
        # Client disconnected -> Close upstream connection immediately
        response.close()
    except Exception:
        response.close()


# --- HELPER FOR MP4 HEADERS ---
def get_proxied_headers(response_headers):
    """Passes necessary headers for VLC seeking."""
    headers_to_send = {}
    allowed = [
        "content-type",
        "content-length",
        "content-range",
        "accept-ranges",
        "last-modified",
    ]
    for k, v in response_headers.items():
        if k.lower() in allowed:
            headers_to_send[k] = v
    headers_to_send["Accept-Ranges"] = "bytes"
    return headers_to_send


@app.route("/")
def index():
    """Main route to check if server is running."""
    return "Proxy server is running."


@app.route("/stream")
def stream_video():
    """Route to start streaming a video."""
    url = request.args.get("url")
    headers_str = request.args.get("headers", "{}")

    if not url:
        return "Missing URL", 400

    try:
        headers = json.loads(headers_str)
    except json.JSONDecodeError:
        headers = {}

    current_config["url"] = url
    current_config["headers"] = headers

    client_range = request.headers.get("Range")
    if client_range:
        headers["Range"] = client_range

    ext = request.args.get("ext")
    return get_m3u8(url, headers, ext=ext)


@app.route("/playlist.m3u8")
def proxy_m3u8():
    """Entry point if the server is called directly for the current stream."""
    if not current_config["url"]:
        return "No stream configured", 404
    return get_m3u8(current_config["url"], current_config["headers"])


def get_m3u8(target_url, headers, ext=None):
    try:
        # 1. Download using the retry wrapper
        response = requests_retry_session(target_url, headers)

        # Allow 206 (Partial Content) for MP4 seeking
        if response.status_code not in [200, 206]:
            return f"Error retrieving: {response.status_code}", 500

        if ext == "mp4":
            proxied_headers = get_proxied_headers(response.headers)
            return Response(
                stream_with_context(safe_iter_content(response)),
                status=response.status_code,
                headers=proxied_headers,
                content_type=response.headers.get("Content-Type"),
                direct_passthrough=True,
            )

        # 2. Sniff content to detect M3U8
        # We read the first chunk to check for #EXTM3U
        iterator = response.iter_content()
        try:
            first_chunk = next(iterator)
        except StopIteration:
            return "", 200

        if first_chunk.strip().startswith(b"#EXTM3U"):
            # It is an M3U8 playlist
            content = first_chunk + b"".join(iterator)

            # Decode safely
            try:
                original_content = content.decode("utf-8")
            except:
                original_content = content.decode("latin-1")

            base_url = get_base_url(target_url)
            new_lines = []

            for line in original_content.splitlines():
                line = line.strip()
                if not line:
                    continue

                # Rewrite Encryption Keys
                if line.startswith("#EXT-X-KEY"):

                    def replace_key_uri(match):
                        key_url = match.group(1)
                        absolute_key_url = urllib.parse.urljoin(base_url, key_url)
                        encoded_key_url = urllib.parse.quote(absolute_key_url)
                        return f'URI="{request.host_url}proxy?url={encoded_key_url}"'

                    line = re.sub(r'URI="(.*?)"', replace_key_uri, line)
                    new_lines.append(line)

                # Rewrite Segments/Links
                elif not line.startswith("#"):
                    absolute_url = urllib.parse.urljoin(base_url, line)
                    encoded_url = urllib.parse.quote(absolute_url)
                    proxy_line = f"{request.host_url}proxy?url={encoded_url}"
                    new_lines.append(proxy_line)
                else:
                    new_lines.append(line)

            return Response(
                "\n".join(new_lines), mimetype="application/vnd.apple.mpegurl"
            )

        else:
            # It's not M3U8 (likely video segment or MP4 fallback)
            # Reconstruct the stream
            def generate():
                yield first_chunk
                yield from safe_iter_content(response)

            proxied_headers = get_proxied_headers(response.headers)
            return Response(
                stream_with_context(generate()),
                status=response.status_code,
                headers=proxied_headers,
                content_type=response.headers.get("Content-Type"),
            )

    except Exception as e:
        return f"Server error: {str(e)}", 500


@app.route("/proxy")
def proxy_segment():
    """This route downloads segments (.ts) or sub-playlists."""
    target_url = request.args.get("url")

    if not target_url:
        return "Missing URL", 400

    try:
        headers = current_config["headers"]

        # Use retry session here too (Prevents HLS segments from failing)
        req = requests_retry_session(target_url, headers)

        # Detect sub-playlist
        if "mpegurl" in req.headers.get("Content-Type", "") or target_url.endswith(
            ".m3u8"
        ):
            return get_m3u8(target_url, headers)

        # Stream binary segment
        return Response(
            stream_with_context(safe_iter_content(req)),
            content_type=req.headers.get("Content-Type"),
        )

    except Exception as e:
        return f"Proxy error: {str(e)}", 500


def start_proxy_server(port=5000):
    """Starts the Flask server in a background thread."""
    log = logging.getLogger("werkzeug")
    log.setLevel(logging.ERROR)

    def run():
        app.run(
            host="127.0.0.1", port=port, debug=False, use_reloader=False, threaded=True
        )

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return f"http://127.0.0.1:{port}"


if __name__ == "__main__":
    print(f"Server started manually.")

    current_config = {
        "url": "https://x1y90gywrmdo.tnmr.org/hls2/03/02373/,8fsszo8urxx1_h,lang/fre/8fsszo8urxx1_fre,lang/eng/8fsszo8urxx1_eng,.urlset/master.m3u8?t=7ODEdPpdnrkMx0ASotRfkG0xuZ2WI1YNmhNmxHX0Q_0&s=1764533924&e=28800&f=11868918&i=0.3&sp=0&fr=8fsszo8urxx1",
        "headers": {
            "Referer": "https://lulustream.com/",
            "Origin": "https://lulustream.com",
            "Host": "x1y90gywrmdo.tnmr.org",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:145.0) Gecko/20100101 Firefox/145.0",
            "Accept": "*/*",
            "Accept-Language": "fr-FR,en-US;q=0.7,en;q=0.3",
            "Accept-Encoding": "gzip, deflate, br, zstd",
            "Sec-GPC": "1",
            "Connection": "keep-alive",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "cross-site",
        },
    }

    app.run(host="0.0.0.0", port=5000, debug=True, threaded=True)
