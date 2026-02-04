import json
import re
from curl_cffi import requests


def strip_json_comments(json_str: str) -> str:
    """
    Remove // comments from JSON string.
    """
    # Regex to remove // comments but preserve URLs like http://
    # Matches // not preceded by : (to avoid http://) and until end of line
    pattern = r"(?<!:)\/\/.*$"
    return re.sub(pattern, "", json_str, flags=re.MULTILINE)


def strip_trailing_commas(json_str: str) -> str:
    """
    Remove trailing commas from JSON objects and arrays.
    """
    return re.sub(r",\s*([\]}])", r"\1", json_str)


def load_remote_jsonc(url: str, default: dict) -> dict:
    """
    Fetch a remote JSONC file, strip comments, and parse it.
    Returns the default dictionary if fetching or parsing fails.
    """
    try:
        response = requests.get(url, impersonate="chrome", timeout=5)
        response.raise_for_status()

        # Simple comment stripping
        clean_json = strip_json_comments(response.text)
        clean_json = strip_trailing_commas(clean_json)

        return json.loads(clean_json)
    except Exception as e:
        print(f"Warning: Failed to load remote config from {url}: {e}")
        return default
