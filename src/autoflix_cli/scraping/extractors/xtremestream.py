def get_hls_link_xtremestream(url, headers, config: dict = None):
    """Point the xtremestream player page at its direct stream endpoint.

    Pure URL rewrite (``/player/index.php?data=`` -> ``/player/xs1.php?data=``),
    so this extractor needs no imports. The playlist itself requires the
    embed-host Referer, which the proxy/direct launch modes already send.
    """
    data_id = url.split("?data=")[1]
    url_root = url.removeprefix("https://").removesuffix("http://").split("/")[0]

    return f"https://{url_root}/player/xs1.php?data={data_id}"
