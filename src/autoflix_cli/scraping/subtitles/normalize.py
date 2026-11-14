"""Turn whatever a provider serves into a clean SRT/VTT track.

Keyless subtitle endpoints are messy: the stremio.homes add-on wraps an SRT
file in a VTT envelope (two ``WEBVTT`` headers), prefixes a promotional cue,
and some uploads are CP1252, UTF-16, gzip, xz or zip. Players are much more
forgiving than a browser ``<track>``, so the CLI normalizes everything before
handing it over: one header, UTF-8, comma timestamps for SRT, no ad cue.
"""

from __future__ import annotations

import bz2
import gzip
import html
import io
import lzma
import re
import zipfile

_TIMESTAMP = re.compile(
    r"(?:(\d{1,2}):)?(\d{1,2}):(\d{1,2})[.,](\d{1,3})"
)
_ASS_DIALOGUE = re.compile(r"^Dialogue:\s*(.*)$", re.IGNORECASE)
_AD_MARKERS = (
    "opensubtitles",
    "subscene",
    "addic7ed",
    "yify",
    "osdb",
    "v3+ v0.0.4",
)
_ASS_OVERRIDE = re.compile(r"\{[^}]*\}")
_VTT_INLINE_TIME = re.compile(r"<\d{1,2}:\d{2}(?::\d{2})?\.\d{1,3}>")


def decompress(data: bytes, url: str = "") -> bytes:
    """Undo the compression wrappers seen in subtitle feeds."""
    path = (url or "").split("?")[0].lower()
    try:
        if data[:2] == b"\x1f\x8b" or path.endswith(".gz"):
            return gzip.decompress(data)
        if data[:6] == b"\xfd7zXZ\x00" or path.endswith(".xz"):
            return lzma.decompress(data)
        if data[:3] == b"BZh" or path.endswith(".bz2"):
            return bz2.decompress(data)
        if data[:2] == b"PK" or path.endswith(".zip"):
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                for name in archive.namelist():
                    if name.lower().endswith((".srt", ".vtt", ".ass", ".ssa", ".sub")):
                        return archive.read(name)
    except Exception:  # noqa: BLE001 - keep the raw bytes on a bad archive
        return data
    return data


def decode_text(data: bytes) -> str:
    """Decode subtitle bytes, honouring BOMs and legacy Windows encodings."""
    for bom, encoding in (
        (b"\xef\xbb\xbf", "utf-8-sig"),
        (b"\xff\xfe", "utf-16"),
        (b"\xfe\xff", "utf-16"),
    ):
        if data.startswith(bom):
            try:
                return data.decode(encoding)
            except UnicodeDecodeError:
                break
    for encoding in ("utf-8", "cp1252", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def sniff_format(text: str, url: str = "") -> str:
    """Best guess between srt/vtt/ass from the payload, then the URL."""
    head = text.lstrip("\ufeff \t\r\n")[:4096]
    lowered = head.lower()
    if lowered.startswith("webvtt"):
        return "vtt"
    if "[script info]" in lowered or "[events]" in lowered or "\ndialogue:" in lowered:
        return "ass"
    timestamp = re.search(r"\d{1,2}:\d{2}:\d{2}([.,])\d{1,3}\s*-->", head)
    if timestamp:
        return "srt" if timestamp.group(1) == "," else "vtt"
    path = (url or "").split("?")[0].lower()
    for extension in (".ass", ".ssa", ".vtt", ".srt", ".sub"):
        if extension in path:
            return extension[1:]
    return "srt"


def _parse_timestamp(value: str) -> float | None:
    match = _TIMESTAMP.search(value or "")
    if not match:
        return None
    hours = int(match.group(1) or 0)
    minutes = int(match.group(2))
    seconds = int(match.group(3))
    millis = int(match.group(4).ljust(3, "0")[:3])
    return hours * 3600 + minutes * 60 + seconds + millis / 1000


def _format_timestamp(seconds: float, separator: str) -> str:
    seconds = max(0.0, seconds)
    millis = int(round(seconds * 1000))
    hours, millis = divmod(millis, 3_600_000)
    minutes, millis = divmod(millis, 60_000)
    secs, millis = divmod(millis, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}{separator}{millis:03d}"


def _clean_text(value: str, *, vtt: bool = False) -> str:
    value = html.unescape(value or "")
    value = _VTT_INLINE_TIME.sub("", value)
    if vtt:
        # VTT cue classes/voices are not useful once the file is normalized.
        value = re.sub(r"</?(?:c|v|lang)(?:\.[^ >]+)?(?:\s[^>]*)?>", "", value)
    value = value.replace("\r", "")
    lines = [line.strip() for line in value.split("\n")]
    return "\n".join(line for line in lines if line).strip()


def _is_ad(text: str) -> bool:
    lowered = text.strip().lower()
    if not lowered:
        return True
    if lowered in ("header", "webvtt"):
        return True
    if lowered.startswith("=>") and ".srt" in lowered:
        return True
    return any(marker in lowered for marker in _AD_MARKERS)


def _cues_from_srt_or_vtt(text: str, *, vtt: bool) -> list[tuple[float, float, str]]:
    text = text.replace("\ufeff", "").replace("\r\n", "\n").replace("\r", "\n")
    cues: list[tuple[float, float, str]] = []
    for block in re.split(r"\n{2,}", text):
        lines = [line for line in block.split("\n") if line.strip()]
        if not lines:
            continue
        arrow_index = next(
            (index for index, line in enumerate(lines) if "-->" in line), None
        )
        if arrow_index is None:
            continue
        start_raw, _, end_raw = lines[arrow_index].partition("-->")
        start = _parse_timestamp(start_raw)
        end = _parse_timestamp(end_raw)
        if start is None or end is None or end <= start:
            continue
        body = _clean_text("\n".join(lines[arrow_index + 1 :]), vtt=vtt)
        if _is_ad(body):
            continue
        cues.append((start, end, body))
    return cues


def _cues_from_ass(text: str) -> list[tuple[float, float, str]]:
    cues: list[tuple[float, float, str]] = []
    fields = ["layer", "start", "end", "style", "name", "marginl", "marginr", "marginv", "effect", "text"]
    in_events = False
    for line in text.replace("\r\n", "\n").split("\n"):
        stripped = line.strip()
        if stripped.lower().startswith("[events]"):
            in_events = True
            continue
        if stripped.startswith("[") and in_events:
            in_events = False
        if not in_events:
            continue
        if stripped.lower().startswith("format:"):
            fields = [part.strip().lower() for part in stripped.split(":", 1)[1].split(",")]
            continue
        match = _ASS_DIALOGUE.match(stripped)
        if not match:
            continue
        parts = match.group(1).split(",", len(fields) - 1)
        if len(parts) < len(fields):
            continue
        record = dict(zip(fields, parts, strict=False))
        start = _parse_timestamp(record.get("start", ""))
        end = _parse_timestamp(record.get("end", ""))
        if start is None or end is None or end <= start:
            continue
        body = _ASS_OVERRIDE.sub("", record.get("text", ""))
        body = body.replace("\\N", "\n").replace("\\n", "\n").replace("\\h", " ")
        body = _clean_text(body)
        if _is_ad(body):
            continue
        cues.append((start, end, body))
    return cues


def parse_cues(text: str, fmt: str | None = None) -> list[tuple[float, float, str]]:
    """Parse any supported subtitle text into ``(start, end, text)`` cues."""
    fmt = (fmt or sniff_format(text)).lower()
    if fmt in ("ass", "ssa"):
        return _cues_from_ass(text)
    return _cues_from_srt_or_vtt(text, vtt=fmt == "vtt")


def to_srt(data: bytes, url: str = "") -> str:
    """Normalize any payload into clean UTF-8 SRT text."""
    text = decode_text(decompress(data, url))
    fmt = sniff_format(text, url)
    cues = parse_cues(text, fmt)
    blocks = []
    for index, (start, end, body) in enumerate(cues, start=1):
        blocks.append(
            f"{index}\n"
            f"{_format_timestamp(start, ',')} --> {_format_timestamp(end, ',')}\n"
            f"{body}"
        )
    return "\n\n".join(blocks) + ("\n" if blocks else "")


def to_vtt(data: bytes, url: str = "") -> str:
    """Normalize any payload into a single-header WebVTT document."""
    text = decode_text(decompress(data, url))
    fmt = sniff_format(text, url)
    cues = parse_cues(text, fmt)
    blocks = ["WEBVTT"]
    for start, end, body in cues:
        blocks.append(
            f"{_format_timestamp(start, '.')} --> {_format_timestamp(end, '.')}\n{body}"
        )
    return "\n\n".join(blocks) + "\n"


def looks_like_subtitle(data: bytes) -> bool:
    """Reject HTML error pages before they become a text track."""
    head = data[:400].lstrip().lower()
    if head.startswith(b"<!doctype html") or head.startswith(b"<html"):
        return False
    if b"<body" in head:
        return False
    return True
