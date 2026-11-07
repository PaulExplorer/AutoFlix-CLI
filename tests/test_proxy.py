import pathlib
import urllib.parse

import pytest

from autoflix_cli import proxy
from autoflix_cli.scraping.pipelines import xtremestream as xs


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
    import os
    import tempfile

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


def test_rewrite_m3u8_propagates_playlist_token_to_tokenless_children(proxy_port):
    """StreamHide-family CDNs sign only the playlists; their bare segment
    paths start answering 403 once the authorization window closes. The web
    player appends the playlist query to every child request, the proxy must
    too (the tokenized segment keeps working while the bare one is dead)."""
    playlist_url = "https://cdn.example.com/hls2/01/master.m3u8?t=TOK&s=1&e=2"
    content = (
        "#EXTM3U\n"
        "#EXTINF:10.0,\n"
        "https://cdn.example.com/hls2/01/seg-1.ts\n"
        "#EXTINF:10.0,\n"
        "https://cdn.example.com/hls2/01/seg-2.ts?own=1\n"
        "#EXT-X-MAP:URI=\"https://cdn.example.com/hls2/01/init.mp4\"\n"
        "https://other.test/hls2/01/seg-3.ts\n"
    )
    rewritten = proxy._rewrite_m3u8(content, playlist_url, {}, "ts")

    tokenized = proxy.make_segment_proxy_url(
        "https://cdn.example.com/hls2/01/seg-1.ts?t=TOK&s=1&e=2",
        "https://cdn.example.com/hls2/01/",
        {},
    )
    assert tokenized in rewritten
    # A child with its own query is left untouched.
    own_query = proxy.make_segment_proxy_url(
        "https://cdn.example.com/hls2/01/seg-2.ts?own=1",
        "https://cdn.example.com/hls2/01/",
        {},
    )
    assert own_query in rewritten
    # A child on another host does not receive the playlist token.
    other_host = proxy.make_segment_proxy_url(
        "https://other.test/hls2/01/seg-3.ts",
        "https://cdn.example.com/hls2/01/",
        {},
    )
    assert other_host in rewritten


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


# ---------------------------------------------------------------------------
# xtremestream (ftk pipeline)
# ---------------------------------------------------------------------------
import json

from Crypto.Cipher import AES as _AES


def _xs_encrypted(plain: bytes, key: bytes, index: int) -> bytes:
    """AES-CBC sandbag used by the tests: IV = big-endian index + PKCS7 pad."""
    pad = xs.AES.block_size - len(plain) % xs.AES.block_size
    cipher = _AES.new(key, xs.AES.MODE_CBC, iv=index.to_bytes(16, "big"))
    return cipher.encrypt(plain + bytes([pad]) * pad)


def test_xs_xor_filter_recovers_json():
    token = "deadbeef.1793617200"
    data_id = "c37f3680"
    manifest = {"720": {"durs": [10, 4.4]}, "audio": [], "cdn": ["h1"]}
    plain = json.dumps(manifest).encode()
    payload = bytes(
        b ^ d
        for b, d in zip(plain, xs._xs_xor_filter(bytes(len(plain)), data_id, token))
    )
    assert json.loads(xs._xs_xor_filter(payload, data_id, token)) == manifest


def test_xs_variant_names_sorted_by_resolution():
    manifest = {
        "720": {"durs": [10]},
        "1080": {"durs": [10]},
        "480p": {"durs": [10]},
        "audio": [],
        "cdn": ["h1"],
    }
    assert xs._xs_variant_names(manifest) == ["1080", "720", "480p"]


def test_xs_playlist_text_shape():
    text = xs._xs_playlist_text([10, 4.4], 10, lambda i: f"u{i}")
    lines = text.splitlines()
    assert lines[0] == "#EXTM3U"
    assert "#EXT-X-TARGETDURATION:10" in text
    assert "#EXT-X-PLAYLIST-TYPE:VOD" in text
    assert "#EXTINF:10,\nu0" in text
    assert "#EXTINF:4.4,\nu1" in text
    assert text.endswith("#EXT-X-ENDLIST\n")


def test_xs_decrypt_with_index_iv_and_pkcs7():
    key = bytes(range(16))
    plain = b"\x47" + b"TS payload" * 20  # not a multiple of 16
    raw = _xs_encrypted(plain, key, 7)
    assert xs._xs_decrypt(raw, 7, key) == plain


def test_xs_decrypt_rejects_garbage():
    # Wrong key -> no 0x47 sync byte -> ValueError (and not a crash).
    raw = _xs_encrypted(b"\x42" * 64, b"\x00" * 16, 0)
    with pytest.raises(ValueError):
        xs._xs_decrypt(raw, 0, b"\x01" * 16)


MANIFEST = {
    "720": {
        "td": 10,
        "n": 3,
        "durs": [7.12, 3.08, 10],
        "bw": 573020,
        "res": "1280x720",
    },
    "audio": [{"lang": "und", "name": "und", "default": False, "td": 6, "durs": [6, 6]}],
    "cdn": ["h1.tld", "h2.tld"],
}
PLAYER_URL = "https://lecteur1.xtremestream.xyz/player/index.php?data=abc"
PLAYER_URL_Q = urllib.parse.quote(PLAYER_URL, safe="")


@pytest.fixture
def xs_client(monkeypatch):
    monkeypatch.setattr(xs, "_xs_manifest", lambda *a, **k: MANIFEST)
    monkeypatch.setattr(xs, "_xs_key", lambda *a, **k: b"\x01" * 16)
    return proxy.app.test_client()


def test_xs_master_playlist(xs_client):
    url = f"/xs/master?data=abc&u={PLAYER_URL_Q}"
    resp = xs_client.get(url)
    assert resp.status_code == 200
    text = resp.data.decode()
    assert "#EXTM3U" in text
    assert (
        "#EXT-X-STREAM-INF:BANDWIDTH=573020,RESOLUTION=1280x720,AUDIO=\"aud\""
        in text
    )
    assert f'/xs/media?data=abc&u={PLAYER_URL_Q}&q=720' in text
    assert 'TYPE=AUDIO,GROUP-ID="aud"' in text
    assert "DEFAULT=NO" in text  # track["default"] is False


def test_xs_media_playlist(xs_client):
    url = f"/xs/media?data=abc&u={PLAYER_URL_Q}&q=720"
    resp = xs_client.get(url)
    assert resp.status_code == 200
    text = resp.data.decode()
    assert "TARGETDURATION:10" in text
    assert "/xs/segment.ts?data=abc&u=" in text
    assert "&q=720&i=2" in text
    assert "#EXTINF:7.12," in text


def test_xs_audio_playlist(xs_client):
    url = f"/xs/audio?data=abc&u={PLAYER_URL_Q}&lang=und"
    resp = xs_client.get(url)
    assert resp.status_code == 200
    text = resp.data.decode()
    assert "&a=und&i=1" in text
    # Unknown lang -> 404.
    assert xs_client.get("/xs/audio?data=abc&u=x&lang=zz").status_code == 404


def test_xs_media_unknown_quality(xs_client):
    resp = xs_client.get("/xs/media?data=abc&q=666&u=x")
    assert resp.status_code == 404


def test_xs_video_segment_decrypted(xs_client, monkeypatch):
    key = bytes(range(16))
    plain = b"\x47" + b"video data" * 30
    raw = _xs_encrypted(plain, key, 1)
    seen = {}

    def fake_fetch(url, headers, environ=None, client_range=None, max_retries=2):
        seen["url"] = url
        seen["headers"] = headers
        return raw, 200, {}

    monkeypatch.setattr(proxy, "fetch_segment", fake_fetch)
    monkeypatch.setattr(xs, "_xs_key", lambda *a, **k: key)

    resp = xs_client.get(f"/xs/segment.ts?data=abc&u={PLAYER_URL_Q}&q=720&i=1")
    assert resp.status_code == 200
    assert resp.data == plain
    assert resp.headers["Content-Type"] == "video/mp2t"
    # cdn hosts rotate by index modulo: h2 for i=1 of 2 hosts.
    assert seen["url"] == "https://h2.tld/cdn/down/abc/720_enc/7201.html"
    assert seen["headers"] == {"Referer": "https://lecteur1.xtremestream.xyz/"}


def test_xs_video_segment_retries_fresh_key(xs_client, monkeypatch):
    """A garbage decrypt (stale key) triggers one force-refresh attempt."""
    key = bytes(range(16))
    plain = b"\x47" + b"data" * 20
    raw = _xs_encrypted(plain, key, 3)

    monkeypatch.setattr(proxy, "fetch_segment", lambda *a, **k: (raw, 200, {}))
    keys = []

    def fake_key(*args, force=False, **kw):
        keys.append(force)
        return b"\xff" * 16 if len(keys) == 1 else key

    monkeypatch.setattr(xs, "_xs_key", fake_key)
    resp = xs_client.get("/xs/segment.ts?data=abc&u=x&q=720&i=3")
    assert resp.status_code == 200
    assert resp.data == plain
    assert keys == [False, True]


def test_xs_audio_segment_passthrough(xs_client, monkeypatch):
    audio = b"\x47" + b"aac ts" * 20
    seen = {}

    def fake_fetch(url, headers, environ=None, client_range=None, max_retries=2):
        seen["url"] = url
        return audio, 200, {}

    monkeypatch.setattr(proxy, "fetch_segment", fake_fetch)
    resp = xs_client.get("/xs/segment.ts?data=abc&u=x&a=und&i=2")
    assert resp.status_code == 200
    assert resp.data == audio
    assert seen["url"] == "https://h1.tld/cdn/down/abc/hls_audio/und/seg_002.aac"


def test_xs_segment_bad_index_and_missing_params(xs_client):
    assert xs_client.get("/xs/segment.ts?data=abc&u=x&q=720&i=zz").status_code == 400
    assert xs_client.get("/xs/segment.ts?data=abc&q=720&i=1").status_code == 400  # no u
    assert xs_client.get("/xs/segment.ts?data=abc&u=x&i=1").status_code == 400  # no q

def test_xs_master_requires_params():
    client = proxy.app.test_client()
    assert client.get("/xs/master").status_code == 400

