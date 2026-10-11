from .xupload import get_hls_link_xupload

def get_hls_link_vidzy(embed_url: str, headers: dict, config: dict = None) -> str | None:
    """Legacy alias: Vidzy now uses the shared XUpload extractor."""
    return get_hls_link_xupload(embed_url, headers, config)
