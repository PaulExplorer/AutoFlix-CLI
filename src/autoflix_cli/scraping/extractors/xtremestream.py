import urllib.parse

from ... import proxy as _proxy


def get_hls_link_xtremestream(url, headers, config: dict = None):
    """Emit the local /xs/master pipeline URL for an xtremestream player page.

    There is no public playlist to point at anymore: the page boots XSFTK
    with a signed token and the manifest/key/segments go through
    ``proto_api.php`` plus AES-encrypted CDN files (see the ftk section in
    proxy.py). The proxy routes materialize the real playlists and decrypt
    the video segments, so the player just loads the local URL directly.
    """
    if "?data=" not in url:
        return None
    data_id = url.split("?data=")[-1].split("&")[0]
    if not data_id:
        return None

    if not _proxy.PROXY_PORT:
        _proxy.start_proxy_server()

    return (
        f"http://{_proxy.PROXY_HOST}:{_proxy.PROXY_PORT}/xs/master"
        f"?data={urllib.parse.quote(data_id, safe='')}"
        f"&u={urllib.parse.quote(url, safe='')}"
    )
