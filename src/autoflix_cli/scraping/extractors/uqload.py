from .default import get_hls_link_default

def get_hls_link_uqload(url: str, headers: dict, config: dict = None) -> str | None:
    """Extract HLS link from uqload players.

    uqload serves the same XUpload/jwplayer templates as the rest of the
    family now (packed ``sources:[{file:...}]`` or the legacy
    ``sources: ["..."]`` form), so this delegates to the default extractor,
    which also retries an allowlisted Referer when the embed is restricted.
    """
    return get_hls_link_default(url, headers, config)
