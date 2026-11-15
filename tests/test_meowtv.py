"""MeowTV is a JSON API: one single-use ticket per request, one entry per server.

The subtitle list is served by its own endpoint and is attached to every
entry, so the existing "embedded tracks" menu keeps working.
"""

from autoflix_cli.scraping.meowtv import MeowTVExtractor


def _payloads(monkeypatch, extractor, streams, subtitles=None):
    def fake_get_json(path):
        if path.startswith("/subs"):
            return subtitles or []
        for marker, payload in streams.items():
            if marker in path:
                return payload
        return None

    monkeypatch.setattr(extractor, "_get_json", fake_get_json)


def test_streams_build_one_entry_per_server(monkeypatch):
    extractor = MeowTVExtractor()
    _payloads(
        monkeypatch,
        extractor,
        {
            "s=dcloud": {"encrypted": "auto"},
            "s=english": {"encrypted": "eng"},
        },
    )

    def decrypt(data):
        if not data:
            return None
        if data["encrypted"] == "auto":
            return {"language": "Auto", "url": "https://cdn.example/a.m3u8"}
        return {
            "language": "English",
            "url": "https://cdn.example/b.m3u8",
            "headers": {"Referer": "https://cdn.example/"},
        }

    monkeypatch.setattr(extractor, "_decrypt", decrypt)

    results = extractor.streams(42994)

    assert [r["source"] for r in results] == [
        "MeowTV (dcloud - Auto)",
        "MeowTV (english - English)",
    ]
    assert [r["type"] for r in results] == ["M3U8", "M3U8"]
    # Per-server headers win over the generic ones.
    assert results[1]["headers"]["Referer"] == "https://cdn.example/"


def test_servers_without_the_title_are_skipped(monkeypatch):
    extractor = MeowTVExtractor()
    _payloads(monkeypatch, extractor, {"s=dcloud": None})
    monkeypatch.setattr(extractor, "_decrypt", lambda data: None)

    assert extractor.streams(42994) == []


def test_duplicate_urls_are_dropped(monkeypatch):
    extractor = MeowTVExtractor()
    _payloads(
        monkeypatch,
        extractor,
        {"s=dcloud": {"e": 1}, "s=english": {"e": 1}, "s=tik": {"e": 1}},
    )
    monkeypatch.setattr(
        extractor,
        "_decrypt",
        lambda data: {"language": "Auto", "url": "https://cdn.example/same.m3u8"},
    )

    results = extractor.streams(42994)

    assert len(results) == 1


def test_tv_path_uses_the_season_and_episode(monkeypatch):
    extractor = MeowTVExtractor()
    seen = []

    def fake_get_json(path):
        seen.append(path)
        return None

    monkeypatch.setattr(extractor, "_get_json", fake_get_json)

    extractor.streams(209867, season=1, episode=3)

    assert "/streams/tv/209867/1/3?s=dcloud" in seen
    assert "/subs/tv/209867/1/3" in seen


def test_movie_path_has_no_season(monkeypatch):
    extractor = MeowTVExtractor()
    seen = []
    monkeypatch.setattr(
        extractor, "_get_json", lambda path: seen.append(path) or None
    )

    extractor.streams(42994)

    assert "/subs/movie/42994" in seen
    assert "/streams/movie/42994?s=dcloud" in seen


def test_subtitles_are_normalised_and_deduplicated(monkeypatch):
    extractor = MeowTVExtractor()
    _payloads(
        monkeypatch,
        extractor,
        {},
        subtitles=[
            {"label": "French", "file": "https://cdn.example/fr.vtt"},
            {"label": "French", "file": "https://cdn.example/fr.vtt"},
            {"label": "Broken"},
        ],
    )

    tracks = extractor.subtitles(42994)

    assert len(tracks) == 1
    assert tracks[0]["lang"] == "French"
    assert tracks[0]["format"] == "vtt"
    assert tracks[0]["headers"]["Referer"] == "https://meowtv.ru/"


def test_streams_without_tmdb_id_skip_the_network(monkeypatch):
    extractor = MeowTVExtractor()

    def boom(path):
        raise AssertionError("no request expected")

    monkeypatch.setattr(extractor, "_get_json", boom)

    assert extractor.streams(None) == []
    assert extractor.subtitles(None) == []
