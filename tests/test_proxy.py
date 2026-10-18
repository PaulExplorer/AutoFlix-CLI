import pathlib
import urllib.parse

import pytest

from autoflix_cli import proxy


def test_is_blocked_page():
    assert proxy._is_blocked_page(b"")
    assert proxy._is_blocked_page(b"   <html>")
    assert proxy._is_blocked_page(b"<!DOCTYPE html>")
    assert proxy._is_blocked_page(b"<script>")
    # TS segment payload starts with the 0x47 sync byte, even when the
    # server (wrongly) claims text/html.
    assert not proxy._is_blocked_page(b"\x47\x40\x00\x10", "text/html")
    assert not proxy._is_blocked_page(b"random binary data")


def test_is_allowed_subtitle_path(tmp_path):
    import tempfile
    import os

    fd, allowed = tempfile.mkstemp(prefix="autoflix_sub_", suffix=".srt")
    os.close(fd)
    try:
        assert proxy._is_allowed_subtitle_path(allowed)
    finally:
        os.remove(allowed)

    assert not proxy._is_allowed_subtitle_path("/etc/passwd")
    assert not proxy._is_allowed_subtitle_path(None)
    assert not proxy._is_allowed_subtitle_path("")
    # Right prefix but outside the temp dir (pytest's tmp_path lives
    # inside the temp dir, so use the repo itself as the outsider).
    outside = pathlib.Path(__file__).resolve().parent / "autoflix_sub_evil.srt"
    assert not proxy._is_allowed_subtitle_path(str(outside))


@pytest.fixture
def proxy_port():
    old = proxy.PROXY_PORT
    proxy.PROXY_PORT = 1234
    try:
        yield 1234
    finally:
        proxy.PROXY_PORT = old


def test_rewrite_m3u8_proxies_bare_uris(proxy_port):
    content = (
        "#EXTM3U\n"
        "#EXT-X-VERSION:3\n"
        "https://cdn.example.com/low.m3u8\n"
        "#EXTINF:10.0,\n"
        "https://cdn.example.com/seg1.ts\n"
    )
    rewritten = proxy._rewrite_m3u8(
        content, "https://cdn.example.com/master.m3u8", {}, "stream"
    )

    def proxied(uri, endpoint):
        quoted = urllib.parse.quote(uri)
        return f"http://127.0.0.1:{proxy_port}/{endpoint}?url={quoted}"

    assert proxied("https://cdn.example.com/low.m3u8", "stream") in rewritten
    assert proxied("https://cdn.example.com/seg1.ts", "stream") in rewritten


def test_rewrite_m3u8_proxies_uri_attributes(proxy_port):
    content = (
        '#EXT-X-KEY:METHOD=AES-128,URI="https://cdn.example.com/key.bin",IV=0x1\n'
        "#EXT-X-MAP:URI=\"https://cdn.example.com/init.mp4\"\n"
    )
    rewritten = proxy._rewrite_m3u8(
        content, "https://cdn.example.com/master.m3u8", {}, "stream"
    )

    # Keys and init segments are binary payloads: they go through /ts, keeping
    # their upstream extension in the proxied path so ffmpeg's
    # allowed_segment_extensions check passes.
    expected_key = proxy.make_segment_proxy_url(
        "https://cdn.example.com/key.bin", "https://cdn.example.com/", {}
    )
    expected_map = proxy.make_segment_proxy_url(
        "https://cdn.example.com/init.mp4", "https://cdn.example.com/", {}
    )
    assert f'URI="{expected_key}"' in rewritten
    assert f'URI="{expected_map}"' in rewritten


def test_rewrite_m3u8_leaves_already_proxied_urls(proxy_port):
    already = f"http://127.0.0.1:{proxy_port}/ts?url=x"
    content = f"#EXTINF:10.0,\n{already}\n"
    rewritten = proxy._rewrite_m3u8(
        content, "https://cdn.example.com/m.m3u8", {}, "stream"
    )
    assert already in rewritten


def test_rewrite_m3u8_keeps_original_bytes(proxy_port):
    content = "#EXTM3U\r\n#EXT-X-VERSION:3\r\nhttps://cdn.example.com/a.ts\r\n"
    rewritten = proxy._rewrite_m3u8(
        content, "https://cdn.example.com/m.m3u8", {}, "stream"
    )
    assert "\r\n" in rewritten
    assert rewritten.startswith("#EXTM3U\r\n")


def test_segment_urls_keep_upstream_extension(proxy_port):
    """ffmpeg's HLS demuxer validates the segment URL *extension*.

    A proxied URL ending in `/ts?url=...` has none, and ffmpeg then fails the
    whole playlist with "not in allowed_segment_extensions". The extension must
    therefore survive into the proxied path.
    """
    content = (
        "#EXTM3U\n"
        "#EXTINF:10.0,\n"
        "https://cdn.example.com/seg1.ts\n"
        "#EXTINF:10.0,\n"
        "https://cdn.example.com/seg2.m4s\n"
        "#EXTINF:10.0,\n"
        "https://cdn.example.com/seg3.mp4\n"
    )
    rewritten = proxy._rewrite_m3u8(
        content, "https://cdn.example.com/media.m3u8", {}, "ts"
    )
    assert "/ts/segment.ts?url=" in rewritten
    assert "/ts/segment.m4s?url=" in rewritten
    assert "/ts/segment.mp4?url=" in rewritten
    # No segment may point at the extensionless legacy route.
    assert "/ts?url=" not in rewritten


def test_segment_extension_ignores_query_string():
    """Signed CDN URLs put everything after `?`; the path still ends in .ts."""
    url = "https://cdn.example.com/hls/seg1.ts?sig=abc&e=12345"
    assert proxy._segment_extension(url) == "ts"


def test_segment_extension_defaults_to_ts():
    # xtremestream serves real TS under an .html extension; MPEG-TS is the safe
    # default because Content-Type is derived from this value.
    assert proxy._segment_extension("https://x.com/a/seg.html") == "ts"
    assert proxy._segment_extension("https://x.com/seg") == "ts"


def test_segment_content_types_cover_known_extensions():
    assert proxy.SEGMENT_CONTENT_TYPES["ts"] == "video/mp2t"
    assert proxy.SEGMENT_CONTENT_TYPES["m4s"] == "video/iso.segment"
    assert proxy.SEGMENT_CONTENT_TYPES["mp4"] == "video/mp4"
    # Unknown extensions must never fall back to a wrong fMP4 type.
    assert "html" not in proxy.SEGMENT_CONTENT_TYPES


# callistanise (minochinos CDN) hides its TS segments inside fake PNG images:
# a tiny 1x1 header (~70 bytes, ending with IEND+CRC) followed by real media
# bytes, served as image/png from signed tiktokcdn URLs. The fixtures below
# reproduce that shape with synthetic data.
_FAKE_PNG_HEAD = (
    b"\x89PNG\r\n\x1a\n"
    b"\x00\x00\x00\x0dIHDR"
    b"\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
    b"\x00\x00\x00\x00IEND\xaeB`\x82"
)


def test_strip_image_wrapper_png_ts():
    """TS hidden after a tiny PNG header is unwrapped."""
    ts_payload = b"\x47" + b"\x00" * 187 + b"\x47" + b"\x11" * 200
    wrapped = _FAKE_PNG_HEAD + ts_payload
    stripped = proxy._strip_image_wrapper(wrapped)
    assert stripped == ts_payload
    assert stripped.startswith(b"\x47")


def test_strip_image_wrapper_png_fmp4():
    """fMP4 fragments (ftyp box) wrapped in an image are also unwrapped."""
    payload = b"\x00\x00\x00\x18ftypiso5" + b"\x00" * 128
    assert proxy._strip_image_wrapper(_FAKE_PNG_HEAD + payload) == payload


def test_strip_image_wrapper_leaves_plain_media_alone():
    ts = b"\x47" + b"\x00" * 187 + b"\x47" + b"\x00" * 188
    assert proxy._strip_image_wrapper(ts) == ts

    mp4 = b"\x00\x00\x00\x18ftypiso5" + b"\x00" * 128
    assert proxy._strip_image_wrapper(mp4) == mp4


def test_strip_image_wrapper_leaves_real_images_alone():
    """A genuine PNG payload (no media after IEND) stays untouched."""
    import struct
    import zlib

    ihdr_body = b"\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00"
    ihdr = struct.pack(">I", 13) + b"IHDR" + ihdr_body
    ihdr += struct.pack(">I", zlib.crc32(b"IHDR" + ihdr_body))
    body = b"\x78\x9c\x63\x60\x60\x60\x00\x00\x00\x04\x00\x01"
    idat = struct.pack(">I", len(body)) + b"IDAT" + body
    idat += struct.pack(">I", zlib.crc32(b"IDAT" + body))
    iend = b"\x00\x00\x00\x00IEND\xaeB`\x82"
    real_png = b"\x89PNG\r\n\x1a\n" + ihdr + idat + iend
    tail = b"\x00" * 128  # trailing bytes: no TS sync, no ftyp -> untouched
    assert proxy._strip_image_wrapper(real_png + tail) == real_png + tail


def test_strip_image_wrapper_png_without_iend_kept():
    """Truncated image (no IEND marker): nothing to strip."""
    body = b"\x89PNG\r\n\x1a\n" + b"\x00" * 400
    assert proxy._strip_image_wrapper(body) == body


def test_strip_image_wrapper_png_garbage_tail_kept():
    """IEND present but no TS/fMP4 payload after it: untouched (defensive)."""
    wrapped = _FAKE_PNG_HEAD + b"garbage-after-iend" * 8
    assert proxy._strip_image_wrapper(wrapped) == wrapped
