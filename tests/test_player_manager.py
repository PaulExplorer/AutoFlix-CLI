import json
import urllib.parse

from autoflix_cli import player_manager as pm
from autoflix_cli import proxy


def test_guess_subtitle_ext():
    assert pm._guess_subtitle_ext("https://x.com/a.srt") == ".srt"
    assert pm._guess_subtitle_ext("https://x.com/a.ass") == ".ass"
    assert pm._guess_subtitle_ext("https://x.com/a.vtt.xz") == ".vtt"
    assert pm._guess_subtitle_ext("https://x.com/a.xz") == ".srt"
    assert pm._guess_subtitle_ext("https://x.com/noext") == ".srt"


def test_build_upstream_headers():
    headers = {"User-Agent": "ua"}
    config = {
        "alt-used": True,
        "sec_headers": "A: 1;B: 2",
    }
    built = pm._build_upstream_headers(headers, "https://ref.com/", config, "ref.com")
    assert built == {
        "User-Agent": "ua",
        "Referer": "https://ref.com/",
        "Alt-Used": "ref.com",
        "A": "1",
        "B": "2",
    }


def test_build_upstream_headers_without_optional_values():
    built = pm._build_upstream_headers({}, "", {}, "ref.com")
    assert built == {}


def test_build_proxy_url_format(monkeypatch):
    monkeypatch.setattr(proxy, "PROXY_URL", "http://127.0.0.1:9999")
    proxy_headers = {"Referer": "https://ref.com/"}

    url = pm._build_proxy_url(
        "https://cdn.example.com/seg.m3u8", proxy_headers, {}, False
    )
    expected = (
        "http://127.0.0.1:9999/stream"
        f"?url={urllib.parse.quote('https://cdn.example.com/seg.m3u8')}"
        f"&headers={urllib.parse.quote(json.dumps(proxy_headers))}"
    )
    assert url == expected


def test_build_proxy_url_endpoint_selection(monkeypatch):
    monkeypatch.setattr(proxy, "PROXY_URL", "http://127.0.0.1:9999")
    base = "https://cdn.example.com/seg.mp4"

    mp4_url = pm._build_proxy_url(base, {}, {"ext": "mp4"}, False)
    assert mp4_url.split("?")[0].endswith("/video")
    direct_mp4 = pm._build_proxy_url(base, {}, {}, True)
    assert direct_mp4.split("?")[0].endswith("/video")
    hls = pm._build_proxy_url(base, {}, {}, False)
    assert hls.split("?")[0].endswith("/stream")


def test_build_proxy_url_without_proxy(monkeypatch):
    monkeypatch.setattr(proxy, "PROXY_URL", None)
    assert pm._build_proxy_url("https://x.com/f", {}, {}, False) is None


def test_resolve_stream_direct(monkeypatch):
    monkeypatch.setattr(proxy, "PROXY_URL", None)
    assert pm._resolve_stream("https://x.com/f.mp4", {}, True) == (
        "https://x.com/f.mp4",
        None,
    )
