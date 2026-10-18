"""The shared 'add extra subtitles?' prompt and its playback wiring (no network)."""

import pytest

from autoflix_cli.handlers import playback, subtitle_prompt
from autoflix_cli.scraping.objects import Episode, Player


# --- pure helpers -----------------------------------------------------------


def test_parse_number():
    assert subtitle_prompt.parse_number("Episode 12") == 12
    assert subtitle_prompt.parse_number("E1") == 1
    assert subtitle_prompt.parse_number(7) == 7
    assert subtitle_prompt.parse_number("Movie") is None
    assert subtitle_prompt.parse_number(None) is None


def test_parse_season_requires_a_marker():
    assert subtitle_prompt.parse_season("Saison 2 (VF)") == 2
    assert subtitle_prompt.parse_season("Season 3") == 3
    assert subtitle_prompt.parse_season("S4") == 4
    # A series title reused as a season label must never leak a number.
    assert subtitle_prompt.parse_season("The 100") is None
    assert subtitle_prompt.parse_season("Movie") is None
    assert subtitle_prompt.parse_season(None) is None


def test_describe_subtitle():
    text = subtitle_prompt._describe_subtitle(
        {"source": "OpenSubtitles (Homes)", "label": "French", "title": "Movie"}
    )
    assert "OpenSubtitles (Homes)" in text and "French" in text and "Movie" in text


# --- prompt behaviour -------------------------------------------------------


def _scripted(monkeypatch, answers):
    """Answer ``select_from_list`` calls in order."""
    calls = []

    def fake_select(options, prompt, default_index=0, **kwargs):
        calls.append((prompt, list(options)))
        return answers.pop(0)

    monkeypatch.setattr(subtitle_prompt, "select_from_list", fake_select)
    return calls


class _Response:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


def test_decline_returns_no_tracks(monkeypatch):
    monkeypatch.setattr(subtitle_prompt, "select_from_list", lambda *a, **k: 1)
    searched = {"n": 0}
    monkeypatch.setattr(
        subtitle_prompt.subtitle_extractor,
        "search",
        lambda **k: searched.__setitem__("n", 1) or [],
    )
    assert subtitle_prompt.prompt_extra_subtitles(title="X", imdb_id="tt1") == []
    assert searched["n"] == 0


def test_selects_the_chosen_track(monkeypatch):
    tracks = [
        {"url": "u1", "source": "A", "lang": "fr", "label": "French", "title": "t1"},
        {"url": "u2", "source": "B", "lang": "fr", "label": "French", "title": "t2"},
    ]
    seen = {}
    monkeypatch.setattr(
        subtitle_prompt.subtitle_extractor,
        "search",
        lambda **kw: seen.update(kw) or tracks,
    )
    _scripted(monkeypatch, [0, 1])  # Yes, then the second track

    result = subtitle_prompt.prompt_extra_subtitles(
        title="X", imdb_id="tt1", season=1, episode=2
    )

    assert result == [tracks[1]]
    assert seen["imdb_id"] == "tt1"
    assert seen["season"] == 1
    assert seen["episode"] == 2
    assert seen["anidb_id"] is None


def test_no_results_returns_empty(monkeypatch):
    monkeypatch.setattr(subtitle_prompt.subtitle_extractor, "search", lambda **k: [])
    _scripted(monkeypatch, [0])
    assert subtitle_prompt.prompt_extra_subtitles(title="X", imdb_id="tt1") == []


def test_resolves_imdb_from_title_when_missing(monkeypatch):
    monkeypatch.setattr(subtitle_prompt, "resolve_imdb_id", lambda title: ("tt99", False))
    seen = {}
    monkeypatch.setattr(
        subtitle_prompt.subtitle_extractor,
        "search",
        lambda **kw: seen.update(kw)
        or [{"url": "u", "source": "A", "lang": "fr", "label": "French", "title": ""}],
    )
    _scripted(monkeypatch, [0, 0])

    result = subtitle_prompt.prompt_extra_subtitles(title="Some Show")

    assert result[0]["url"] == "u"
    assert seen["imdb_id"] == "tt99"


def test_movie_resolution_drops_season_and_episode(monkeypatch):
    monkeypatch.setattr(subtitle_prompt, "resolve_imdb_id", lambda title: ("tt7", True))
    seen = {}
    monkeypatch.setattr(
        subtitle_prompt.subtitle_extractor, "search", lambda **kw: seen.update(kw) or []
    )
    _scripted(monkeypatch, [0])

    subtitle_prompt.prompt_extra_subtitles(title="Film", season=1, episode=3)

    assert seen["season"] is None and seen["episode"] is None


def test_anilist_mapping_provides_ids(monkeypatch):
    monkeypatch.setattr(subtitle_prompt, "_anilist_ids", lambda i: ("tt42", 99))
    seen = {}
    monkeypatch.setattr(
        subtitle_prompt.subtitle_extractor, "search", lambda **kw: seen.update(kw) or []
    )
    _scripted(monkeypatch, [0])

    subtitle_prompt.prompt_extra_subtitles(anilist_id=123)

    assert seen["imdb_id"] == "tt42" and seen["anidb_id"] == 99


def test_gives_up_without_any_identifier(monkeypatch):
    _scripted(monkeypatch, [0])
    searched = {"n": 0}
    monkeypatch.setattr(
        subtitle_prompt.subtitle_extractor,
        "search",
        lambda **k: searched.__setitem__("n", 1) or [],
    )
    assert subtitle_prompt.prompt_extra_subtitles(title=None) == []
    assert searched["n"] == 0


# --- Cinemeta / AniList resolution -----------------------------------------


def test_resolve_imdb_id_lists_matches(monkeypatch):
    def fake_get(url, **kwargs):
        if "/series/" in url:
            return _Response(
                {"metas": [{"name": "Show", "year": 2020, "type": "series", "imdb_id": "tt123"}]}
            )
        return _Response(
            {"metas": [{"name": "Show Movie", "year": 2021, "type": "movie", "imdb_id": "tt456"}]}
        )

    monkeypatch.setattr(subtitle_prompt.requests, "get", fake_get)
    _scripted(monkeypatch, [1])  # pick the movie entry

    assert subtitle_prompt.resolve_imdb_id("Show") == ("tt456", True)


def test_resolve_imdb_id_falls_back_to_manual(monkeypatch):
    monkeypatch.setattr(subtitle_prompt.requests, "get", lambda *a, **k: _Response({"metas": []}))
    monkeypatch.setattr(subtitle_prompt, "get_user_input", lambda prompt: "tt999")
    assert subtitle_prompt.resolve_imdb_id("Nothing") == ("tt999", False)


def test_anilist_ids_normalize_numeric_imdb(monkeypatch):
    import autoflix_cli.scraping.goldenanime as scraper

    class _Stub:
        @staticmethod
        def get_mappings(anilist_id):
            return {"imdbId": "12345", "anidbId": 7}

    monkeypatch.setattr(scraper, "goldenanime", _Stub)
    assert subtitle_prompt._anilist_ids(1) == ("tt12345", 7)


# --- playback wiring --------------------------------------------------------


def test_collect_extra_subtitles_derives_series_numbers(monkeypatch):
    seen = {}
    monkeypatch.setattr(
        playback, "prompt_extra_subtitles", lambda **kw: seen.update(kw) or []
    )
    playback._collect_extra_subtitles(
        ask=True,
        title="Show",
        imdb_id=None,
        anidb_id=None,
        anilist_id=None,
        season_title="Saison 3",
        episode=Episode("Episode 7", []),
        season_number=None,
        episode_number=None,
    )
    assert seen["season"] == 3 and seen["episode"] == 7


def test_collect_extra_subtitles_defaults_unknown_season_to_one(monkeypatch):
    seen = {}
    monkeypatch.setattr(
        playback, "prompt_extra_subtitles", lambda **kw: seen.update(kw) or []
    )
    playback._collect_extra_subtitles(
        ask=True,
        title="Show",
        imdb_id=None,
        anidb_id=None,
        anilist_id=None,
        season_title="The 100",  # series title reused as season label
        episode=Episode("Episode 4", []),
        season_number=None,
        episode_number=None,
    )
    assert seen["season"] == 1 and seen["episode"] == 4


def test_collect_extra_subtitles_movie(monkeypatch):
    seen = {}
    monkeypatch.setattr(
        playback, "prompt_extra_subtitles", lambda **kw: seen.update(kw) or []
    )
    playback._collect_extra_subtitles(
        ask=True,
        title="Film",
        imdb_id=None,
        anidb_id=None,
        anilist_id=None,
        season_title="Movie",
        episode=Episode("Some Film (2020)", []),
        season_number=None,
        episode_number=None,
    )
    assert seen["season"] is None and seen["episode"] is None


def test_collect_extra_subtitles_disabled_skips_prompt(monkeypatch):
    called = {"n": 0}
    monkeypatch.setattr(
        playback, "prompt_extra_subtitles",
        lambda **kw: called.__setitem__("n", 1) or [],
    )
    result = playback._collect_extra_subtitles(
        ask=False,
        title="Show",
        imdb_id=None,
        anidb_id=None,
        anilist_id=None,
        season_title="Saison 1",
        episode=Episode("Episode 1", []),
        season_number=None,
        episode_number=None,
    )
    assert result == [] and called["n"] == 0


PLAYER = Player("uqload", "https://uqload.vc/embed-1.html")


def test_play_episode_flow_asks_and_passes_subtitles(monkeypatch):
    track = {"url": "https://sub.example/fr.srt", "source": "Test", "lang": "fr"}
    monkeypatch.setattr(playback.tracker, "get_developer_mode", lambda: False)
    monkeypatch.setattr(playback.tracker, "get_auto_source", lambda: False)
    monkeypatch.setattr(playback.tracker, "save_progress", lambda **kw: None)
    monkeypatch.setattr(playback, "prompt_extra_subtitles", lambda **kw: [track])
    monkeypatch.setattr(playback, "select_from_list", lambda options, prompt, **kw: 0)
    calls = []
    monkeypatch.setattr(playback, "play_video", lambda url, **kw: calls.append(kw) or True)

    result = playback.play_episode_flow(
        provider_name="Test",
        series_title="Series",
        season_title="Saison 2",
        episode=Episode("Episode 5", [PLAYER]),
        series_url="",
        season_url="",
        headers={},
    )

    assert result is True
    assert calls[0]["subtitles"] == [track]
