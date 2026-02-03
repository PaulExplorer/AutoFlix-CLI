from curl_cffi import requests
from .deobfuscate import deobfuscate
from bs4 import BeautifulSoup
from ..proxy import DNS_OPTIONS
from ..config_loader import load_remote_jsonc
from ..defaults import DEFAULT_PLAYERS, DEFAULT_NEW_URL, DEFAULT_KAKAFLIX_PLAYERS
import re, base64

import json
import binascii
from Crypto.Cipher import AES
from Crypto.Util.Padding import unpad

scraper = requests.Session(curl_options=DNS_OPTIONS)

# Player mapping: domain name -> parser type
# Player mapping and configuration
players = load_remote_jsonc(
    "https://raw.githubusercontent.com/PaulExplorer/AutoFlix-CLI/refs/heads/main/data/players_info.jsonc",
    DEFAULT_PLAYERS,
)

# URL replacements for compatibility
new_url = load_remote_jsonc(
    "https://raw.githubusercontent.com/PaulExplorer/AutoFlix-CLI/refs/heads/main/data/new_url.jsonc",
    DEFAULT_NEW_URL,
)

# kakaflix supported players
kakaflix_players = load_remote_jsonc(
    "https://raw.githubusercontent.com/PaulExplorer/AutoFlix-CLI/refs/heads/main/data/kakaflix_players.jsonc",
    DEFAULT_KAKAFLIX_PLAYERS,
)


def extract_hls_url(unpacked_code):
    pattern = r'["\'](https?://[^"\']*master\.txt[^"\']*)["\']'
    match = re.search(pattern, unpacked_code)
    if match:
        return match.group(1)

    pattern = r'["\'](https?://[^"\']*master\.m3u8[^"\']*)["\']'
    match = re.search(pattern, unpacked_code)
    if match:
        return match.group(1)

    return None


def get_hls_link_default(url: str, headers: dict) -> str:
    response = scraper.get(url, headers=headers, impersonate="chrome")
    response.raise_for_status()

    code = deobfuscate(response.text)

    return extract_hls_url(code)


def get_hls_link_embed4me(embed_url: str) -> str:
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

    r = scraper.get(api_url, headers=headers, impersonate="chrome", timeout=10)
    r.raise_for_status()

    hex_data = r.text.strip()
    if hex_data.startswith('"') and hex_data.endswith('"'):
        hex_data = hex_data[1:-1]

    decrypted = _decrypt_data(hex_data)

    data = json.loads(decrypted)
    source = data.get("source")
    return source


def get_hls_link_uqload(url: str, headers: dict) -> str:
    """
    Extract HLS link from uqload players.

    Args:
        url: Player URL
        headers: HTTP headers for the request

    Returns:
        HLS stream URL
    """
    response = scraper.get(
        url.replace("embed-", ""),
        headers={**headers, "Referer": "https://uqload.cx/"},
        impersonate="chrome",
    )
    response.raise_for_status()

    link = response.text.split('sources: ["')[1].split('"')[0]

    return link


def get_hls_link_sendvid(url: str) -> str:
    """
    Extract video link from sendvid using Open Graph meta tag.

    Args:
        url: Player URL

    Returns:
        Video URL
    """
    response = scraper.get(url, impersonate="chrome")
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")

    link: str = soup.find("meta", {"property": "og:video"}).attrs["content"]

    return link


def get_hls_link_sibnet(url: str) -> str:
    """
    Extract video link from sibnet.

    Args:
        url: Player URL

    Returns:
        Video URL
    """
    response = scraper.get(url, impersonate="chrome")
    response.raise_for_status()

    relative_path = response.text.split('player.src([{src: "')[1].split('"')[0]
    link = "https://video.sibnet.ru" + relative_path

    return link


def get_hls_link_filemoon(url: str, headers: dict) -> str:
    """
    Extract HLS link from filemoon players.
    Follows iframe redirect and deobfuscates JavaScript.

    Args:
        url: Player URL

    Returns:
        HLS stream URL
    """

    def decode_base64(text):
        """Decodes URL-safe Base64 with proper padding."""
        if not text:
            return b""
        # Add padding if necessary and decode
        return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))

    def try_decrypt(key, iv, full_payload):
        """Tries to decrypt the payload using two common GCM tag positions."""

        # Combination 1: Authentication Tag at the end (Standard AES-GCM)
        try:
            ciphertext = full_payload[:-16]
            tag = full_payload[-16:]
            cipher = AES.new(key, AES.MODE_GCM, nonce=iv)
            return cipher.decrypt_and_verify(ciphertext, tag).decode("utf-8")
        except Exception:
            pass

        # Combination 2: Authentication Tag at the beginning
        try:
            tag = full_payload[:16]
            ciphertext = full_payload[16:]
            cipher = AES.new(key, AES.MODE_GCM, nonce=iv)
            return cipher.decrypt_and_verify(ciphertext, tag).decode("utf-8")
        except Exception:
            pass

        return None

    def solve_decryption(json_str):
        """Parses the JSON and attempts multiple key combinations for decryption."""
        data = json.loads(json_str)
        playback = data.get("playback", {})

        # 1. Prepare potential keys
        key_parts = playback.get("key_parts", [])
        decrypt_keys = playback.get("decrypt_keys", {})

        potential_keys = []

        # Hypothesis A: Concatenate key_parts[0] + key_parts[1]
        if len(key_parts) >= 2:
            part0 = decode_base64(key_parts[0])
            part1 = decode_base64(key_parts[1])
            potential_keys.append(part0 + part1)
            potential_keys.append(part1 + part0)

        # Hypothesis B: Concatenate edge_1 + edge_2 (16 + 16 = 32 bytes for AES-256)
        if "edge_1" in decrypt_keys and "edge_2" in decrypt_keys:
            edge1 = decode_base64(decrypt_keys["edge_1"])
            edge2 = decode_base64(decrypt_keys["edge_2"])
            potential_keys.append(edge1 + edge2)

        # 2. Prepare data
        iv = decode_base64(playback.get("iv"))
        payload = decode_base64(playback.get("payload"))

        # 3. Test all key combinations
        for i, key in enumerate(potential_keys):
            result = try_decrypt(key, iv, payload)
            if result:
                return result

        print("Error: No valid decryption found.")
        return None

    code = url.split("/")[-1]
    response = scraper.get(
        "https://9n8o.com/api/videos/" + code + "/embed/playback",
        impersonate="chrome",
        headers={
            "Referer": "https://9n8o.com/g1x/" + code + "/",
            "X-Embed-Origin": headers["Referer"]
            .removeprefix("https://")
            .removesuffix("/"),
            "X-Embed-Parent": "https://filemoon.sx/e/" + code,
            "X-Embed-Referer": headers["Referer"],
        },
    )
    response.raise_for_status()

    decrypted_json_str = solve_decryption(response.text)
    if decrypted_json_str:
        video_data = json.loads(decrypted_json_str)
        video_url = video_data["sources"][0]["url"]
        return video_url
    else:
        return get_hls_link(url, headers)


def get_hls_link_vidoza(url: str, headers: dict) -> str:
    """
    Extract HLS link from vidoza players.

    Args:
        url: Player URL
        headers: HTTP headers for the request

    Returns:
        HLS stream URL
    """

    response = scraper.get(
        url,
        headers=headers,
        impersonate="chrome",
    )
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")

    link: str = soup.find("source").attrs["src"]

    return link


def get_hls_link_kakaflix(url: str, headers: dict) -> str:
    """
    Extract HLS link from kakaflix players.

    Args:
        url: Player URL
        headers: HTTP headers for the request

    Returns:
        HLS stream URL
    """
    response = scraper.get(
        url,
        headers=headers,
        impersonate="chrome",
    )
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")

    try:
        link: str = soup.find("iframe").attrs["src"]
    except:
        return get_hls_link(response.url, headers)
    else:
        return get_hls_link(link, headers)


def get_hls_link_myvidplay(url: str, headers: dict) -> str:
    """
    Extract HLS link from myvidplay players.

    Args:
        url: Player URL
        headers: HTTP headers for the request

    Returns:
        HLS stream URL
    """
    response = scraper.get(
        url,
        headers=headers,
        impersonate="chrome",
    )
    response.raise_for_status()

    link = response.text.split("vtt: '")[1].split("'")[0]

    return link


def get_hls_link_vidmoly(url: str, headers: dict) -> str:
    """
    Dedicated parser for Vidmoly to bypass transitional page.
    Mimics an iframe request behavior.
    """
    # Specific headers observed in browser iframe test
    vidmoly_headers = {
        "Sec-Fetch-Dest": "iframe",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "cross-site",
        "Upgrade-Insecure-Requests": "1",
        # Explicitly removing Referer as data: URL worked without it
        "Referer": "",
    }

    # Merge but prioritize our specific headers
    final_headers = {**headers, **vidmoly_headers}
    # Ensure Referer is actually removed if we mapped it to empty string/None
    if "Referer" in final_headers and not final_headers["Referer"]:
        del final_headers["Referer"]

    response = scraper.get(
        url,
        headers=final_headers,
        impersonate="chrome",
    )
    response.raise_for_status()

    return extract_hls_url(response.text)


def get_hls_link_veev(url):
    """
    Extract HLS link from Veev players.
    Converted from https://github.com/phisher98/cloudstream-extensions-phisher/blob/master/Coflix/src/main/kotlin/com/Coflix/Extractor.kt

    Args:
        url: Player URL

    Returns:
        HLS stream URL or None if extraction fails
    """

    # 1. Extract Media ID
    media_id_match = re.search(
        r"(?://|\.)(?:veev|kinoger|poophq|doods)\.(?:to|pw|com)/[ed]/([0-9A-Za-z]+)",
        url,
    )
    if not media_id_match:
        return None
    media_id = media_id_match.group(1)

    # 2. Fetch HTML
    try:
        html = scraper.get(f"https://veev.to/e/{media_id}", impersonate="chrome").text
    except Exception as e:
        print(f"Connection error: {e}")
        return None

    # 3. Extract encrypted tokens
    enc_regex = r"""[.\s'](?:fc|_vvto\[[^]]*)(?:['\]]*)?\s*[:=]\s*['"]([^'"]+)"""
    found_values = re.findall(enc_regex, html)
    if not found_values:
        return None

    # --- Internal helper functions ---
    def veev_decode(etext):
        # LZW-style decompression algorithm
        lut = {i: chr(i) for i in range(256)}
        n = 256
        c = etext[0]
        result = [c]
        for char in etext[1:]:
            code = ord(char)
            entry = lut[code] if code in lut else c + c[0]
            result.append(entry)
            lut[n] = c + entry[0]
            n += 1
            c = entry
        return "".join(result)

    def parse_rules(encoded):
        # We only take the first "row" of rules, matching Kotlin's buildArray(ch)[0]
        it = iter(encoded)

        def next_int():
            try:
                char = next(it)
                return int(char) if char.isdigit() else 0
            except StopIteration:
                return 0

        count = next_int()
        if count == 0:
            return []
        row = [next_int() for _ in range(count)]
        return row[::-1]  # Reversed as in the Kotlin code

    def decode_final(encoded, rules):
        text = encoded
        for r in rules:
            if r == 1:
                text = text[::-1]  # Reverse string
            try:
                # Hex to Bytes to UTF-8
                text = bytes.fromhex(text).decode("utf-8")
            except ValueError:
                pass  # Avoid crash if hex is invalid
            text = text.replace("dXRmOA==", "")  # Remove salt
        return text

    # 4. Main loop
    for f in reversed(found_values):
        ch = veev_decode(f)
        if ch == f:
            continue  # If decoding didn't change anything, skip

        # API call to get JSON
        dl_url = f"https://veev.to/dl?op=player_api&cmd=gi&file_code={media_id}&r=https://veev.to&ch={ch}&ie=1"
        try:
            resp = scraper.get(dl_url, impersonate="chrome").json()
        except:
            continue

        file_obj = resp.get("file")
        if not isinstance(file_obj, dict) or file_obj.get("file_status") != "OK":
            continue

        # Kotlin equivalent: file.getJSONArray("dv")
        dv_list = file_obj.get("dv")

        # Verify it is indeed a list and not empty
        if not dv_list or not isinstance(dv_list, list):
            continue

        # Kotlin equivalent: .getJSONObject(0).getString("s")
        dv_string = dv_list[0].get("s")

        if not dv_string:
            continue

        # Final decoding steps
        step1 = veev_decode(dv_string)
        rules = parse_rules(ch)  # Rules come from 'ch'
        final_link = decode_final(step1, rules)

        return final_link

    return None


def get_hls_link_xtremestream(url, headers):
    data_id = url.split("?data=")[1]
    url_root = url.removeprefix("https://").removesuffix("http://").split("/")[0]

    return f"https://{url_root}/player/xs1.php?data={data_id}"


def get_hls_link(url: str, headers: dict = {}) -> str | None:
    """
    Extract HLS/video link from a player URL.
    Automatically detects the player type and uses the appropriate parser.

    Args:
        url: Player URL
        headers: HTTP headers for the request (default: {})

    Returns:
        HLS/video stream URL if successful, None otherwise
    """

    # Find matching player and parse accordingly
    for player_name, config in players.items():
        if player_name in url.lower():
            parse_type = config["type"]
            if parse_type == "default":
                return get_hls_link_default(url, headers)
            elif parse_type == "sendvid":
                return get_hls_link_sendvid(url)
            elif parse_type == "sibnet":
                return get_hls_link_sibnet(url)
            elif parse_type == "uqload":
                return get_hls_link_uqload(url, headers)
            elif parse_type == "vidoza":
                return get_hls_link_vidoza(url, headers)
            elif parse_type == "filemoon":
                return get_hls_link_filemoon(url, headers)
            elif parse_type == "kakaflix":
                return get_hls_link_kakaflix(url, headers)
            elif parse_type == "myvidplay":
                return get_hls_link_myvidplay(url, headers)
            elif parse_type == "vidmoly":
                return get_hls_link_vidmoly(url, headers)
            elif parse_type == "embed4me":
                return get_hls_link_embed4me(url)
            elif parse_type == "veev":
                return get_hls_link_veev(url)
            elif parse_type == "xtremestream":
                return get_hls_link_xtremestream(url, headers)

    return None


def is_supported(url: str) -> bool:
    """
    Check if a player URL is supported.

    Args:
        url: Player URL to check

    Returns:
        True if the player is supported, False otherwise
    """
    for player in players.keys():
        if "kakaflix" in url.lower():
            for player in kakaflix_players.keys():
                if player in url.lower():
                    return True
            return False

        elif player in url.lower():
            return True

    return False
