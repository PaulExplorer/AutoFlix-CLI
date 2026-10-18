"""Offline tests for the repaired extractors (no network)."""

import base64

from autoflix_cli.scraping import player
from autoflix_cli.scraping.extractors import common, filemoon, uqload, xupload


def _xupload_blob(url: str, hostname: str, width_n: int | None) -> str:
    """Craft an XUpload-style blob encoding ``url`` (mirrors the web player)."""
    seed = sum(hostname.encode()) & 255
    bc = (96 + width_n) // 2 if width_n is not None else 0
    raw = bytes(
        char ^ ((0x3D + i * 89 + seed + bc) & 255)
        for i, char in enumerate(url.encode())
    )[::-1]
    return base64.b64encode(raw).decode()


class _StubResponse:
    def __init__(self, text, url):
        self.text = text
        self.url = url
        self.status_code = 200

    def raise_for_status(self):
        pass


def _stub_fetch(monkeypatch, html, url="https://vidzy.cc/embed-abc123.html"):
    monkeypatch.setattr(
        xupload, "_fetch_embed_page", lambda u, h: _StubResponse(html, url)
    )


def test_player_reexports_extractors():
    """The dispatcher keeps exposing extractor functions (backward compat)."""
    assert player.get_hls_link_xupload is xupload.get_hls_link_xupload
    assert player.get_hls_link_default is not None
    assert set(player.PLAYER_EXTRACTORS) >= {
        "default", "xupload", "vidzy", "filemoon", "uqload", "voe",
    }


def test_xupload_decode_with_width_constant(monkeypatch):
    stream = "https://u14.vidzy.cc/hls2/02/00046/abc123_o/master.m3u8?t=tok"
    blob = _xupload_blob(stream, "vidzy.cc", 126)
    html = (
        "player = videojs('vjsplayer', {sources: [{src: (function(s){"
        "var h=(location&&location.hostname)||\"\",H=0;"
        "var BC=0;try{var _p=document.createElement(\"div\");"
        "_p.style.cssText=\"position:absolute;width:calc(1in + 126px)\";"
        "BC=_ch.offsetWidth|0;}catch(e){}"
        "var b=atob(s),a=b.split(\"\").reverse().join(\"\"),r=\"\";"
        "for(var i=0;i<a.length;i++){var kk=(0x3d+i*89+H+BC)&255;"
        "r+=String.fromCharCode(a.charCodeAt(i)^kk)}"
        "return r})(\"" + blob + "\"), type: \"application/x-mpegURL\"}]});"
    )
    _stub_fetch(monkeypatch, html)
    assert xupload.get_hls_link_xupload("https://vidzy.cc/embed-abc123.html", {}) == stream


def test_xupload_decode_brute_force_without_width(monkeypatch):
    # Browser check present but width constant unreadable: BC is brute-forced.
    stream = "https://r1.fsvid.lol/hls2/03/00025/xyz_o/master.m3u8?t=tok"
    blob = _xupload_blob(stream, "fsvid.lol", 100)
    html = (
        'sources: [{src: (function(s){var BC=0;'
        'try{BC=_ch.offsetWidth|0;}catch(e){}return atob(s)})("' + blob + '")}]'
    )
    _stub_fetch(monkeypatch, html, "https://fsvid.lol/embed-xyz.html")
    assert xupload.get_hls_link_xupload("https://fsvid.lol/embed-xyz.html", {}) == stream


def test_xupload_returns_none_without_blob(monkeypatch):
    _stub_fetch(monkeypatch, "<html><body>no player here</body></html>")
    assert xupload.get_hls_link_xupload("https://vidzy.cc/embed-abc.html", {}) is None


def test_streamhide_links_priority_and_relative():
    html = (
        'jwplayer("vjsplayer").setup({sources:[{file:links.hls4||links.hls3||links.hls2}]});'
        'links={"hls4":"/stream/abc/def/123/master.m3u8",'
        '"hls3":"https://cdn.example.com/h3/master.txt",'
        '"hls2":"https://cdn.example.com/h2/master.m3u8"}'
    )
    assert (
        common._extract_streamhide_links(html, "https://wishonly.site/e/xyz")
        == "https://wishonly.site/stream/abc/def/123/master.m3u8"
    )


def test_streamhide_links_falls_back_to_hls2():
    html = 'links={"hls2":"https://cdn.example.com/h2/master.m3u8"}'
    assert (
        common._extract_streamhide_links(html, "https://x.test/e/1")
        == "https://cdn.example.com/h2/master.m3u8"
    )


def test_streamhide_links_invalid_json():
    assert common._extract_streamhide_links("links={not json", "https://x/") is None
    assert common._extract_streamhide_links("no links here", "https://x/") is None


def test_streamhide_candidates_priority_order():
    html = (
        'links={"hls2":"https://a.test/h2/master.m3u8",'
        '"hls4":"/stream/x/y/z/master.txt",'
        '"hls3":"https://b.test/h3/master.txt"}'
    )
    assert common._extract_streamhide_candidates(html, "https://wishonly.site/e/x") == [
        "https://wishonly.site/stream/x/y/z/master.txt",
        "https://b.test/h3/master.txt",
        "https://a.test/h2/master.m3u8",
    ]


def test_jwplayer_source_absolute_and_relative():
    assert (
        common._extract_jwplayer_source(
            'setup({sources:[{file:"https://cdn.example.com/v/master.m3u8"}]})',
            "https://x.test/e/1",
        )
        == "https://cdn.example.com/v/master.m3u8"
    )
    assert (
        common._extract_jwplayer_source(
            "sources:[{file:'/s/abc/master.m3u8'}]", "https://uqload.cx/embed-1.html"
        )
        == "https://uqload.cx/s/abc/master.m3u8"
    )


def test_filemoon_select_parts_versioned():
    parts = [f"part-{i}" for i in range(30)]
    playback = {"version": "7"}
    assert filemoon._filemoon_select_parts(playback, parts) == ["part-6", "part-23"]
    playback = {"version": "1"}
    assert filemoon._filemoon_select_parts(playback, parts) == ["part-0", "part-29"]


def test_filemoon_select_parts_unknown_version_keeps_all():
    parts = ["a", "b"]
    assert filemoon._filemoon_select_parts({"version": "99"}, parts) == parts
    assert filemoon._filemoon_select_parts({}, parts) == parts
    short = ["only-one"]
    assert filemoon._filemoon_select_parts({"version": "7"}, short) == short


def test_uqload_delegates_to_default(monkeypatch):
    seen = {}

    def fake_default(url, headers, config=None, _depth=0):
        seen["url"] = url
        return "https://cdn.example.com/master.m3u8"

    monkeypatch.setattr(uqload, "get_hls_link_default", fake_default)
    assert (
        uqload.get_hls_link_uqload("https://uqload.cx/embed-abc.html", {})
        == "https://cdn.example.com/master.m3u8"
    )
    assert seen["url"] == "https://uqload.cx/embed-abc.html"
