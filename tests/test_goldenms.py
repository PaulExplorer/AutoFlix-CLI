"""GoldenMS now resolves ids through the keyless TMDB proxy.

The search keeps a Cinemeta fallback, and season menus can be built from
Cinemeta ``videos`` or from TMDB when the former is empty.
"""

from autoflix_cli.handlers import goldenms as handler
from autoflix_cli.scraping import metadata


def test_search_titles_uses_tmdb_first(monkeypatch):
    monkeypatch.setattr(
        metadata,
        "search_titles",
        lambda title, is_movie, year=None: [
            {
                "tmdb_id": 42994,
                "title": "Memories",
                "year": 1995,
                "is_movie": True,
                "imdb_id": "tt0113799",
            }
        ],
    )
    monkeypatch.setattr(
        metadata,
        "cinemeta_candidates",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("fallback used")),
    )

    results = handler.search_titles("Memories", is_movie=True)

    assert results == [
        {
            "name": "Memories",
            "title": "Memories",
            "year": 1995,
            "releaseInfo": "1995",
            "imdb_id": "tt0113799",
            "tmdb_id": 42994,
            "is_movie": True,
            "poster": None,
        }
    ]


def test_search_titles_falls_back_to_cinemeta(monkeypatch):
    monkeypatch.setattr(metadata, "search_titles", lambda *a, **k: [])
    monkeypatch.setattr(
        metadata,
        "cinemeta_candidates",
        lambda title, is_movie, year=None: [
            {
                "imdb_id": "tt0113799",
                "title": "Memories",
                "year": 1995,
                "is_movie": True,
            }
        ],
    )

    results = handler.search_titles("Memories", is_movie=True)

    assert results[0]["imdb_id"] == "tt0113799"
    assert results[0]["tmdb_id"] is None


def test_season_map_from_videos_skips_specials_and_sorts():
    videos = [
        {"season": 1, "episode": 2, "name": "Second"},
        {"season": 0, "episode": 1, "name": "Special"},
        {"season": 1, "episode": 1, "name": "First"},
        {"season": 2, "episode": 0, "name": "Broken"},
        {"season": "2", "episode": "1", "name": "S2E1"},
    ]

    assert handler._season_map_from_videos(videos) == {
        1: [(1, "First"), (2, "Second")],
        2: [(1, "S2E1")],
    }


def test_season_map_from_tmdb_uses_metadata(monkeypatch):
    monkeypatch.setattr(metadata, "tmdb_seasons", lambda tmdb_id: [1, 2])
    monkeypatch.setattr(
        metadata,
        "tmdb_season_episodes",
        lambda tmdb_id, season: [
            {"episode": 1, "name": f"S{season}E1"},
            {"episode": 2, "name": ""},
        ],
    )

    assert handler._season_map_from_tmdb(42) == {
        1: [(1, "S1E1"), (2, "Episode 2")],
        2: [(1, "S2E1"), (2, "Episode 2")],
    }


def test_season_map_from_tmdb_without_id_is_empty():
    assert handler._season_map_from_tmdb(None) == {}
