import binascii
import json
import re

from Crypto.Cipher import AES
from Crypto.Util.Padding import unpad

from .common import get_scraper

def get_hls_link_embed4me(embed_url: str, headers: dict = None, config: dict = None) -> str:
    """
    Extract HLS link from embed4me player.
    Code adapted from: https://github.com/SertraFurr/Anime-Sama-Downloader/blob/main/src/utils/extract/extract_embed4me_video_source.py

    Args:
        embed_url: The embed URL of the player.

    Returns:
        The HLS stream URL or None if not found.
    """

    KEY = b"kiemtienmua911ca"
    IV = b"1234567890oiuytr"

    def _decrypt_data(hex_str):
        try:
            data = binascii.unhexlify(hex_str)
            cipher = AES.new(KEY, AES.MODE_CBC, IV)
            decrypted = unpad(cipher.decrypt(data), AES.block_size)
            return decrypted.decode("utf-8")
        except Exception:
            return None

    match = re.search(r"#([a-zA-Z0-9]+)", embed_url)
    if not match:
        match = re.search(r"[?&]id=([a-zA-Z0-9]+)", embed_url)
    if not match:
        return None

    video_id = match.group(1)
    url_root = "https://" + embed_url.split("/")[2]
    api_url = f"{url_root}/api/v1/video?id={video_id}&w=1920&h=1080&r={url_root}"

    headers = {"Referer": url_root}

    r = get_scraper().get(api_url, headers=headers, impersonate="chrome", timeout=10)
    r.raise_for_status()

    hex_data = r.text.strip()
    if hex_data.startswith('"') and hex_data.endswith('"'):
        hex_data = hex_data[1:-1]

    decrypted = _decrypt_data(hex_data)

    data = json.loads(decrypted)
    source = data.get("source")
    return source
