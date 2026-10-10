import struct
import time

import pytest

from autoflix_cli.scraping import stream_probe as sp
from autoflix_cli.scraping.objects import Player


MASTER = """#EXTM3U
#EXT-X-STREAM-INF:BANDWIDTH=4000000,RESOLUTION=1920x1080,CODECS="avc1.640028"
1080/index.m3u8
#EXT-X-STREAM-INF:BANDWIDTH=1500000,RESOLUTION=1280x720
720/index.m3u8
"""

MEDIA = "#EXTM3U\n#EXT-X-TARGETDURATION:10\n#EXTINF:10.0,\nseg1.ts\n"


def mp4_head(width=1920, height=1080):
    """A minimal chunk carrying a well-formed video ``tkhd`` box."""
    body = (
        b"\x00\x00\x00\x07"  # version + flags
        + b"\x00" * 8  # creation / modification
        + b"\x00\x00\x00\x01"  # track id
        + b"\x00" * 4  # reserved
        + b"\x00" * 4  # duration
        + b"\x00" * 8  # reserved
        + b"\x00" * 8  # layer / alt group / volume / reserved
        + b"\x00" * 36  # matrix
    )
    return b"\x00\x00\x00\x20moovtkhd" + body + struct.pack(
        ">II", width << 16, height << 16
    )


def fetch_returning(response, recorder=None):
    def _fetch(url, headers, range_bytes=False, timeout=None):
        if recorder is not None:
            recorder.append((url, range_bytes))
        return response

    return _fetch


def fetch_raising(exc):
    def _fetch(url, headers, range_bytes=False, timeout=None):
        raise exc

    return _fetch


# --- master playlist parsing ------------------------------------------------


def test_parse_master_qualities_sorted_best_first():
    assert sp.parse_master_qualities(MASTER) == [(1080, 4000000), (720, 1500000)]


def test_parse_master_qualities_ignores_media_playlist():
    assert sp.parse_master_qualities(MEDIA) == []


def test_parse_master_qualities_rejects_non_playlist():
    assert sp.parse_master_qualities("<html>challenge</html>") == []


def test_parse_master_qualities_skips_variant_without_signal():
    playlist = "#EXTM3U\n#EXT-X-STREAM-INF:CODECS=\"avc1\"\nlow.m3u8\n"
    assert sp.parse_master_qualities(playlist) == []


def test_parse_master_qualities_survives_bad_bandwidth():
    playlist = "#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=abc,RESOLUTION=1280x720\na.m3u8\n"
    assert sp.parse_master_qualities(playlist) == [(720, 0)]


# --- static classification --------------------------------------------------


def test_guess_kind_uses_config_ext():
    assert sp.guess_kind("https://cdn.tld/stream", {"ext": "mp4"}) == sp.KIND_MP4


def test_guess_kind_from_url():
    assert sp.guess_kind("https://cdn.tld/a.m3u8") == sp.KIND_HLS_MASTER
    assert sp.guess_kind("https://cdn.tld/a.mp4") == sp.KIND_MP4


def test_guess_kind_defaults_to_hls():
    assert sp.guess_kind("https://cdn.tld/whatever") == sp.KIND_HLS_MASTER


# --- mp4 header -------------------------------------------------------------


def test_mp4_height_from_tkhd():
    assert sp._mp4_height(mp4_head()) == 1080


def test_mp4_height_absent_box_returns_none():
    assert sp._mp4_height(b"\x00" * 128) is None


def test_mp4_height_rejects_audio_sized_box():
    # A 2x2 box is not a video track, so it must not be reported as a height.
    assert sp._mp4_height(mp4_head(width=2, height=2)) is None


def test_content_total_from_content_length():
    assert sp._content_total({"Content-Length": "42"}) == 42


def test_content_total_from_range_answer():
    assert sp._content_total({"Content-Range": "bytes 0-1/999"}) == 999


def test_content_total_missing_headers():
    assert sp._content_total({}) == 0


# --- probing ----------------------------------------------------------------


def test_probe_hls_master_reports_variants():
    result = sp.probe_stream(
        "https://cdn.tld/master.m3u8",
        {},
        fetch=fetch_returning(sp.ProbeResponse(200, {}, MASTER.encode())),
    )
    assert result["ok"] is True
    assert result["kind"] == sp.KIND_HLS_MASTER
    assert result["heights"] == [1080, 720]
    assert result["bandwidths"] == [4000000, 1500000]


def test_probe_hls_media_has_no_variant():
    result = sp.probe_stream(
        "https://cdn.tld/media.m3u8",
        {},
        fetch=fetch_returning(sp.ProbeResponse(200, {}, MEDIA.encode())),
    )
    assert result["ok"] is True
    assert result["kind"] == sp.KIND_HLS_MEDIA
    assert result["heights"] == []


def test_probe_mp4_uses_range_and_reports_height():
    calls = []
    response = sp.ProbeResponse(
        206, {"Content-Range": "bytes 0-65535/90000000"}, mp4_head()
    )
    result = sp.probe_stream(
        "https://cdn.tld/movie.mp4",
        {},
        {"ext": "mp4"},
        fetch=fetch_returning(response, calls),
    )
    assert result["ok"] is True
    assert result["kind"] == sp.KIND_MP4
    assert result["heights"] == [1080]
    assert result["size"] == 90000000
    # A range request is what keeps a progressive file from downloading whole.
    assert calls == [("https://cdn.tld/movie.mp4", True)]


def test_probe_mp4_url_serving_playlist_is_reclassified():
    response = sp.ProbeResponse(206, {}, MASTER.encode())
    result = sp.probe_stream(
        "https://cdn.tld/movie.mp4",
        {},
        fetch=fetch_returning(response),
    )
    assert result["kind"] == sp.KIND_HLS_MASTER
    assert result["heights"] == [1080, 720]


def test_probe_http_error_is_dead():
    result = sp.probe_stream(
        "https://cdn.tld/master.m3u8",
        {},
        fetch=fetch_returning(sp.ProbeResponse(403, {}, b"")),
    )
    assert result["ok"] is False
    assert result["error"] == "HTTP 403"


def test_probe_challenge_page_is_blocked_not_hls():
    body = b"<!DOCTYPE html><html><body>Just a moment...</body></html>"
    result = sp.probe_stream(
        "https://cdn.tld/master.m3u8",
        {},
        fetch=fetch_returning(sp.ProbeResponse(200, {}, body)),
    )
    assert result["ok"] is False
    assert result["error"] == "blocked"


def test_probe_transport_error_is_captured():
    result = sp.probe_stream(
        "https://cdn.tld/master.m3u8", {}, fetch=fetch_raising(TimeoutError("slow"))
    )
    assert result["ok"] is False
    assert "TimeoutError" in result["error"]


def test_probe_forwards_timeout_to_the_fetcher():
    seen = {}

    def _fetch(url, headers, range_bytes=False, timeout=None):
        seen["timeout"] = timeout
        return sp.ProbeResponse(200, {}, MEDIA.encode())

    sp.probe_stream("https://cdn.tld/a.m3u8", {}, fetch=_fetch, timeout=3.5)
    assert seen["timeout"] == 3.5


# --- ranking ----------------------------------------------------------------


def make_source(name, ok=True, heights=(), bandwidths=(), size=0, kind=None):
    return sp.ResolvedSource(
        embed_name=name,
        embed_url=f"https://{name}.tld/e/1",
        headers={},
        player_config={},
        ok=ok,
        kind=kind or (sp.KIND_HLS_MASTER if heights else sp.KIND_HLS_MEDIA),
        heights=list(heights),
        bandwidths=list(bandwidths),
        size=size,
    )


def test_rank_sources_puts_best_height_first():
    ranked = sp.rank_sources(
        [
            make_source("p720", heights=[720]),
            make_source("p1080", heights=[1080]),
            make_source("p480", heights=[480]),
        ]
    )
    assert [s.embed_name for s in ranked] == ["p1080", "p720", "p480"]


def test_rank_sources_breaks_height_ties_on_bandwidth():
    ranked = sp.rank_sources(
        [
            make_source("slow", heights=[1080], bandwidths=[2000000]),
            make_source("fast", heights=[1080], bandwidths=[6000000]),
        ]
    )
    assert [s.embed_name for s in ranked] == ["fast", "slow"]


def test_rank_sources_sinks_dead_sources():
    dead = make_source("dead", ok=False, kind=sp.KIND_DEAD)
    ranked = sp.rank_sources([dead, make_source("live", heights=[720])])
    assert [s.embed_name for s in ranked] == ["live", "dead"]


# --- labels -----------------------------------------------------------------


def test_quality_label_prefers_height():
    assert make_source("a", heights=[720, 1080]).quality_label == "1080p"


def test_quality_label_falls_back_to_size_for_mp4():
    source = make_source("a", size=450 * 1024 * 1024, kind=sp.KIND_MP4)
    assert source.quality_label == "~450 MB"


def test_quality_label_for_media_playlist():
    assert make_source("a", kind=sp.KIND_HLS_MEDIA).quality_label == "HLS"


def test_menu_label_shows_origin_and_quality():
    source = make_source("VIDA", heights=[1080])
    source.elapsed = 1.25
    assert source.menu_label() == "VIDA · 1080p · HLS · 1.2s"


def test_menu_label_uses_the_source_menu_format():
    # Same shape as the long-standing source list: name, then host.
    source = sp.ResolvedSource(
        embed_name="Lecteur 2",
        embed_url="https://ansembed.net/embed-def.html",
        headers={},
        player_config={},
        ok=True,
        kind=sp.KIND_HLS_MASTER,
        heights=[1080],
        elapsed=0.8,
    )
    assert source.menu_label() == "Lecteur 2 : ansembed · 1080p · HLS · 0.8s"


def test_menu_label_skips_a_host_that_repeats_the_name():
    source = sp.ResolvedSource(
        embed_name="uqload",
        embed_url="https://uqload.vc/embed-1.html",
        headers={},
        player_config={},
        ok=True,
        kind=sp.KIND_HLS_MASTER,
        heights=[720],
    )
    assert source.menu_label() == "uqload · 720p · HLS · 0.0s"


def test_embed_host_label():
    assert sp.embed_host_label("https://sibnet.ru/embed-a.html") == "sibnet"
    assert sp.embed_host_label("https://uqload.vc/e/1") == "uqload"
    assert sp.embed_host_label("montmyoboky:535") == ""


def test_fresh_source_is_not_stale():
    source = make_source("a")
    source.probed_at = time.monotonic()
    assert source.is_stale is False


def test_old_source_is_stale():
    source = make_source("a")
    source.probed_at = time.monotonic() - sp.STALE_AFTER - 1
    assert source.is_stale is True


# --- parallel resolution ----------------------------------------------------


@pytest.fixture
def fake_get_hls_link(monkeypatch):
    """Map an embed URL to a stream URL, or to None when it is dead."""
    routes = {}

    def _get_hls_link(url, headers=None, return_subs=False):
        stream = routes.get(url)
        if stream is None:
            return (None, None) if return_subs else None
        if return_subs:
            return stream, None
        return stream

    monkeypatch.setattr(sp.player, "get_hls_link", _get_hls_link)
    return routes


def test_probe_sources_ranks_and_keeps_dead_embeds(fake_get_hls_link, monkeypatch):
    monkeypatch.setattr(sp.player, "match_player_config", lambda url: ({}, ""))

    good = Player("good", "https://good.tld/e/1")
    best = Player("best", "https://best.tld/e/1")
    dead = Player("dead", "https://dead.tld/e/1")
    fake_get_hls_link[good.url] = "https://cdn.tld/720.m3u8"
    fake_get_hls_link[best.url] = "https://cdn.tld/1080.m3u8"

    monkeypatch.setattr(
        sp,
        "probe_stream",
        lambda url, headers, config, fetch=None, timeout=None: {
            "ok": True,
            "kind": sp.KIND_HLS_MASTER if url.endswith("1080.m3u8") else sp.KIND_HLS_MEDIA,
            "heights": [1080] if url.endswith("1080.m3u8") else [],
            "bandwidths": [],
            "size": 0,
        },
    )

    ranked = sp.probe_sources([good, dead, best], {}, fetch=None)

    assert [s.embed_name for s in ranked] == ["best", "good", "dead"]
    assert ranked[-1].ok is False
    assert ranked[-1].error == "no stream found"
    assert ranked[0].stream_url == "https://cdn.tld/1080.m3u8"


def test_probe_sources_reports_progress(fake_get_hls_link, monkeypatch):
    monkeypatch.setattr(sp.player, "match_player_config", lambda url: ({}, ""))
    monkeypatch.setattr(
        sp,
        "probe_stream",
        lambda url, headers, config, fetch=None, timeout=None: {
            "ok": True,
            "kind": sp.KIND_HLS_MEDIA,
            "heights": [],
            "bandwidths": [],
            "size": 0,
        },
    )
    embeds = [Player(f"p{i}", f"https://p{i}.tld/e/1") for i in range(3)]
    for embed in embeds:
        fake_get_hls_link[embed.url] = "https://cdn.tld/media.m3u8"

    started, done = [], []
    sp.probe_sources(
        embeds, {}, on_start=started.append, on_done=lambda s: done.append(s)
    )

    assert sorted(started) == ["p0", "p1", "p2"]
    assert len(done) == 3


def test_probe_sources_on_empty_input():
    assert sp.probe_sources([]) == []