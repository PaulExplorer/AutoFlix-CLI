"""Episode offsets between AniList entries and the TVDB season numbering."""

from autoflix_cli.handlers import goldenanime as handler


def _mappings(**overrides):
    base = {
        "thetvdbId": 267440,
        "defaultTvdbSeason": 4,
        "episodes": 12,
        "franchise": [],
    }
    base.update(overrides)
    return base


def test_explicit_episode_offset_wins(monkeypatch):
    monkeypatch.setattr(handler, "_mapping_ids", lambda aid: {})
    assert handler._episode_offset(_mappings(episodeOffset=16)) == 16


def test_split_cour_sums_prequels_of_the_same_season(monkeypatch):
    prequels = {
        110277: _mappings(defaultTvdbSeason=4, episodes=16),
        104578: _mappings(defaultTvdbSeason=3, episodes=10),
    }
    monkeypatch.setattr(handler, "_mapping_ids", lambda aid: prequels.get(aid, {}))
    mappings = _mappings(
        franchise=[
            {"relation": "PREQUEL", "anilistId": 110277, "format": "TV"},
            {"relation": "PREQUEL", "anilistId": 104578, "format": "TV"},
        ]
    )
    assert handler._episode_offset(mappings) == 16


def test_new_tvdb_season_has_no_offset(monkeypatch):
    prequels = {
        154587: _mappings(thetvdbId=424536, defaultTvdbSeason=1, episodes=28)
    }
    monkeypatch.setattr(handler, "_mapping_ids", lambda aid: prequels.get(aid, {}))
    mappings = _mappings(
        thetvdbId=424536,
        defaultTvdbSeason=2,
        episodes=10,
        franchise=[{"relation": "PREQUEL", "anilistId": 154587, "format": "TV"}],
    )
    assert handler._episode_offset(mappings) == 0


def test_prequels_from_another_show_are_ignored(monkeypatch):
    prequels = {1: _mappings(thetvdbId=999, defaultTvdbSeason=4, episodes=50)}
    monkeypatch.setattr(handler, "_mapping_ids", lambda aid: prequels.get(aid, {}))
    mappings = _mappings(
        franchise=[{"relation": "PREQUEL", "anilistId": 1, "format": "TV"}]
    )
    assert handler._episode_offset(mappings) == 0


def test_movies_are_not_summed(monkeypatch):
    prequels = {1: _mappings(defaultTvdbSeason=4, episodes=2)}
    monkeypatch.setattr(handler, "_mapping_ids", lambda aid: prequels.get(aid, {}))
    mappings = _mappings(
        franchise=[{"relation": "PREQUEL", "anilistId": 1, "format": "MOVIE"}]
    )
    assert handler._episode_offset(mappings) == 0


def test_missing_tvdb_id_returns_zero():
    assert handler._episode_offset({"defaultTvdbSeason": 4}) == 0


def test_subtitle_episode_offsets_only_the_mapped_season(monkeypatch):
    monkeypatch.setattr(handler, "_episode_offset", lambda mappings: 16)
    mappings = _mappings()
    assert handler._subtitle_episode(1, 4, 4, mappings) == 17
    assert handler._subtitle_episode(1, 5, 4, mappings) == 1
