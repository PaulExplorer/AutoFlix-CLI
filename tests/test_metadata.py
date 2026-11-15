"""Offline tests for the keyless TMDB title resolver."""

import pytest

from autoflix_cli.scraping import metadata


@pytest.fixture(autouse=True)
def _clear_cache():
    metadata._cache.clear()
    yield
    metadata._cache.clear()


def test_year_from_title():
    assert metadata.year_from_title("Memories (1995)") == 1995
    assert metadata.year_from_title("Memories") is None


def test_normalize_title_ignores_accents_and_punctuation():
    assert metadata.normalize_title("Le Voyage de Chihiro") == "le voyage de chihiro"
    assert metadata.normalize_title("Amélie (2001)") == "amelie"
    assert metadata.normalize_title("Spider-Man: No Way Home") == "spider man no way home"


def test_score_candidate_prefers_exact_title_and_year():
    exact = {"title": "Memories", "year": 1995, "is_movie": True}
    series = {"title": "Plastic Memories", "year": 2015, "is_movie": False}

    assert metadata.score_candidate(
        "Memories", 1995, True, exact
    ) > metadata.score_candidate("Memories", 1995, True, series)


def test_score_candidate_penalises_wrong_media_type():
    movie = {"title": "Memories", "year": 1995, "is_movie": True}
    series = {"title": "Memories", "year": 1995, "is_movie": False}

    assert metadata.score_candidate("Memories", 1995, True, movie) > (
        metadata.score_candidate("Memories", 1995, True, series)
    )


def test_search_titles_ranks_and_attaches_imdb_ids(monkeypatch):
    def fake_get(path, params=None):
        if path == "search/movie":
            return {
                "results": [
                    {"id": 1, "title": "Memories of Murder", "release_date": "2003-01-01"},
                    {"id": 2, "title": "Memories", "release_date": "1995-12-23"},
                ]
            }
        if path == "movie/2/external_ids":
            return {"imdb_id": "tt0113799"}
        if path == "movie/1/external_ids":
            return {"imdb_id": "tt0353969"}
        return {}

    monkeypatch.setattr(metadata, "_tmdb_get", fake_get)

    results = metadata.search_titles("Memories", is_movie=True, year=1995)

    assert results[0]["imdb_id"] == "tt0113799"
    assert results[0]["is_movie"] is True
    assert [r["imdb_id"] for r in results] == ["tt0113799", "tt0353969"]


def test_resolve_imdb_returns_the_best_match(monkeypatch):
    monkeypatch.setattr(
        metadata,
        "search_titles",
        lambda *a, **k: [
            {"imdb_id": "tt0113799", "title": "Memories", "year": 1995, "is_movie": True}
        ],
    )
    assert metadata.resolve_imdb("Memories") == ("tt0113799", True)


def test_resolve_imdb_returns_none_without_results(monkeypatch):
    monkeypatch.setattr(metadata, "search_titles", lambda *a, **k: [])
    assert metadata.resolve_imdb("Nothing") == (None, None)


def test_find_tmdb_id_prefers_the_requested_media_type(monkeypatch):
    payload = {
        "movie_results": [{"id": 10}],
        "tv_results": [{"id": 20}],
    }
    monkeypatch.setattr(metadata, "_tmdb_get", lambda path, params=None: payload)

    assert metadata.find_tmdb_id("tt0113799", is_movie=True) == 10
    assert metadata.find_tmdb_id("tt0113799", is_movie=False) == 20
    assert metadata.find_tmdb_id("tt0113799") == 10


def test_find_tmdb_id_returns_none_on_failure(monkeypatch):
    def boom(path, params=None):
        raise RuntimeError("down")

    monkeypatch.setattr(metadata, "_tmdb_get", boom)
    assert metadata.find_tmdb_id("tt0113799") is None
    assert metadata.find_tmdb_id("") is None


def test_tmdb_seasons_ignores_specials(monkeypatch):
    monkeypatch.setattr(
        metadata,
        "_tmdb_get",
        lambda path, params=None: {
            "seasons": [
                {"season_number": 0},
                {"season_number": 2},
                {"season_number": 1},
            ]
        },
    )
    assert metadata.tmdb_seasons(42) == [1, 2]


def test_tmdb_season_episodes_returns_names(monkeypatch):
    monkeypatch.setattr(
        metadata,
        "_tmdb_get",
        lambda path, params=None: {
            "episodes": [
                {"episode_number": 2, "name": "Second"},
                {"episode_number": 1, "name": ""},
                {"episode_number": None, "name": "Broken"},
            ]
        },
    )

    assert metadata.tmdb_season_episodes(42, 1) == [
        {"episode": 2, "name": "Second"},
        {"episode": 1, "name": "Episode 1"},
    ]
