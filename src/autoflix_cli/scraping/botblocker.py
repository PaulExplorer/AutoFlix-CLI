import json
import random
import string
from json import JSONDecodeError
from urllib.parse import urlsplit, urlunsplit

_MARKER = "var bbcsJsData = "

_DETECTION_FLAGS = (
    "navigatorMismatch",
    "unsupportedFeatures",
    "fakePlugins",
    "fontRenderMismatch",
    "chromiumProperties",
    "jitter",
    "webGLMismatch",
    "touchEventMismatch",
    "languageMismatch",
    "crossbrowserIncognito",
)


def is_check_page(html: str) -> bool:
    """Return True if the page is a BotBlocker verification page."""
    return _MARKER in html


def _parse_jsdata(html: str):
    idx = html.find(_MARKER)
    if idx == -1:
        return None
    start = idx + len(_MARKER)
    try:
        data, _ = json.JSONDecoder().raw_decode(html[start:])
        return data
    except JSONDecodeError:
        return None


def _build_post(data: dict) -> dict:
    fingerprint = "".join(
        random.choice(string.ascii_lowercase + string.digits) for _ in range(10)
    )

    post = {
        "action": "bbcs_botblocker_check",
        "nonce": data["nonce"],
        data["selectRequestMode"]: "botblocker-security",
        "test": data["testHash"],
        "h1": data["h1Hash"],
        "date": str(data["time"]),
        "hdc": data["hosting"],
        "a": "0",
        "country": data["country"],
        "ip": data["ip"],
        "version": data["version"],
        "cid": data["cid"],
        "ptr": data["ptr"],
        "w": "1920",
        "h": "1080",
        "cw": "1920",
        "ch": "969",
        "co": "24",
        "pi": "24",
        "ref": "",
        "accept": data["httpAccept"],
        "tz": "Europe/Paris",
        "ipdbc": "-",
        "ipv4": "",
        "rct": "",
        "cookieoff": "0",
        "xxx": "",
        "rowid": "0",
        "from_suspect": str(data.get("suspectStatus", "0")),
        "suspect_reason": "null",
        "check_result": data.get("resultOfAction", "No cookies users(Human?)"),
        "browserFingerprint": fingerprint,
    }

    for flag in _DETECTION_FLAGS:
        post[flag] = "false"

    return post


def _origin(url: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, "", "", ""))


def solve(session, html: str, url: str) -> bool:
    """
    Resolve a BotBlocker verification page and store the session cookie.

    Args:
        session: The curl_cffi session used for scraping
        html: The verification page HTML
        url: The URL that returned the verification page

    Returns:
        True if the challenge was solved, False otherwise
    """
    data = _parse_jsdata(html)
    if not data:
        return False

    post = _build_post(data)
    origin = _origin(url)

    headers = {
        "Accept": "*/*",
        "Accept-Language": "fr-FR,en-US;q=0.7,en;q=0.3",
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "X-Requested-With": "XMLHttpRequest",
        "Origin": origin,
        "Referer": origin + "/",
    }

    endpoints = [data.get("ajaxUrl"), data.get("verifyUrl")]
    result = None

    for endpoint in endpoints:
        if not endpoint:
            continue
        response = session.post(endpoint, data=post, headers=headers, timeout=30)
        try:
            result = response.json()
        except (ValueError, JSONDecodeError):
            continue
        if isinstance(result, dict) and result.get("cookie"):
            break
        result = None

    if not result or not isinstance(result, dict):
        return False

    cookie = result.get("cookie")
    if not cookie:
        return False

    domain = urlsplit(origin).netloc
    session.cookies.set(
        data["uid"], f"{cookie}-{data['time']}", domain=domain, path="/"
    )
    return True