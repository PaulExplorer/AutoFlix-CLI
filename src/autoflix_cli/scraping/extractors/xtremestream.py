

def get_hls_link_xtremestream(url, headers, config: dict = None):
    data_id = url.split("?data=")[1]
    url_root = url.removeprefix("https://").removesuffix("http://").split("/")[0]

    return f"https://{url_root}/player/xs1.php?data={data_id}"
