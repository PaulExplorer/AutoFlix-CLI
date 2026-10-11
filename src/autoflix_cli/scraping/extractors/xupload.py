import base64
import binascii
import re
import urllib.parse

from .common import _fetch_embed_page, _unpack_all

# The base b64/reverse/XOR decode is adapted from ResolveURL's Vidzy plugin:
# https://github.com/Gujal00/ResolveURL (script.module.resolveurl/lib/resolveurl/plugins/vidzy.py)
# The extra browser-measured term (BC) was reverse-engineered from the live
# embed pages (it is NOT in ResolveURL).

def get_hls_link_xupload(url: str, headers: dict, config: dict = None) -> str | None:
    """Extract the stream from XUpload-based hosts (vidzy, fsvid, uqload...).

    The player setup hides the source in a base64 blob decoded in-browser as::

        b64decode -> reverse -> XOR((0x3D + i*89 + H + BC) & 255)

    where ``H`` is the embed hostname checksum and ``BC`` a measurement the
    page takes in a real browser (``offsetWidth`` of a 50% child inside a
    ``calc(1in + Npx)`` box, i.e. ``BC = (96 + N) / 2`` at standard DPI).
    ``N`` is read from the page itself; when absent, ``BC`` is brute-forced
    (256 tries on ~200 bytes, negligible) and the first ``https?://`` result
    wins. A wrong key yields garbage, never a link.
    """
    response = _fetch_embed_page(url, headers)
    html = response.text
    page_url = str(response.url or url)
    hostname = urllib.parse.urlparse(page_url).hostname or ""

    try:
        unpacked = _unpack_all(html)
    except Exception:
        unpacked = html

    blobs: list[str] = []
    for text in (html, unpacked):
        for found in re.findall(
            r"\}\)\(\s*[\"']([^\"']{50,})[\"']\s*\)", text
        ):
            if found not in blobs:
                blobs.append(found)
    if not blobs:
        return None

    seed = sum(hostname.encode("utf-8", "ignore")) & 255
    width = re.search(r"1in \+ (\d+)px", unpacked)
    bc_values: list[int] = []
    if width:
        bc_values.append((96 + int(width.group(1))) // 2)
    bc_values.extend(bc for bc in range(256) if bc not in bc_values)

    has_browser_check = "offsetWidth" in unpacked or "+BC" in unpacked
    for blob in blobs:
        try:
            raw = base64.b64decode(blob)
        except (binascii.Error, ValueError):
            continue
        raw = raw[::-1]
        for bc in bc_values:
            out = bytes(
                value ^ ((0x3D + i * 89 + seed + bc) & 255)
                for i, value in enumerate(raw)
            )
            try:
                candidate = out.decode("utf-8")
            except UnicodeDecodeError:
                continue
            if re.match(r"^https?://[^\s\"'\\]+$", candidate):
                return candidate
            # Old template without the browser check: only the seed matters.
            if not has_browser_check:
                break
    return None
