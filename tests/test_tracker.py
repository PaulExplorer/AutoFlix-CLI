import json

import pytest

import autoflix_cli.tracker as tracker_module
from autoflix_cli.tracker import ProgressTracker, _entry_sort_key


@pytest.fixture
def tracker(tmp_path, monkeypatch):
    monkeypatch.setattr(tracker_module, "user_data_dir", lambda *a, **k: str(tmp_path))
    return ProgressTracker()


def test_save_progress_roundtrip(tracker):
    tracker.save_progress(
        provider="Coflix",
        series_title="Show",
        season_title="Season 1",
        episode_title="E1",
        series_url="https://site.com/show",
        season_url="https://site.com/show/s1",
        episode_url="https://site.com/show/s1/e1",
    )
    entry = tracker.get_series_progress("Coflix", "Show")
    assert entry is not None
    assert entry["episode_title"] == "E1"
    assert entry["series_url"] == "/show"
    assert entry["season_url"] == "/show/s1"
    assert tracker.get_last_global()["provider"] == "Coflix"


def test_to_relative_only_for_http_urls(tracker):
    assert tracker._to_relative("https://a.com/x?y=1") == "/x?y=1"
    assert tracker._to_relative("anilist:123") == "anilist:123"
    assert tracker._to_relative("") == ""


def test_get_history_sorted_desc(tracker):
    tracker.save_progress("Coflix", "A", "S", "E1", "u", "u", "u")
    tracker.data["history"]["Coflix|B"] = {
        "provider": "Coflix",
        "series_title": "B",
        "season_title": "S",
        "episode_title": "E1",
        "last_watched": "2030-01-01T00:00:00",
    }
    history = tracker.get_history()
    assert [e["series_title"] for e in history] == ["B", "A"]


def test_get_history_survives_malformed_date(tracker):
    tracker.data["history"] = {
        "bad": {"series_title": "bad", "last_watched": "not-a-date"},
        "good": {"series_title": "good", "last_watched": "2024-01-01T00:00:00"},
    }
    history = tracker.get_history()
    assert [e["series_title"] for e in history] == ["good", "bad"]


def test_delete_history_recomputes_last_global(tracker):
    tracker.save_progress("Coflix", "A", "S", "E1", "u", "u", "u")
    tracker.save_progress("Coflix", "B", "S", "E1", "u", "u", "u")
    assert tracker.get_last_global()["series_title"] == "B"

    tracker.delete_history_item("Coflix", "B")
    assert tracker.get_last_global()["series_title"] == "A"

    tracker.delete_history_item("Coflix", "A")
    assert tracker.get_last_global() is None


def test_corrupt_data_file_is_backed_up(tracker, tmp_path):
    data_file = tmp_path / "progress.json"
    data_file.write_text("{not json", encoding="utf-8")
    fresh = ProgressTracker()
    assert fresh.data == {}
    assert (tmp_path / "progress.json.bak").exists()


def test_entry_sort_key_fallback():
    assert _entry_sort_key({}) .year == 1
    assert _entry_sort_key({"last_watched": "2024-01-01T00:00:00"}) > _entry_sort_key({})


def test_ask_subtitles_defaults_and_toggles(tracker):
    assert tracker.get_ask_subtitles() is True
    tracker.set_ask_subtitles(False)
    assert tracker.get_ask_subtitles() is False
    tracker.set_ask_subtitles(True)
    assert tracker.get_ask_subtitles() is True


def test_sama_lang_pref_default_and_roundtrip(tracker):
    assert tracker.get_sama_lang_pref() == "manual"
    for pref in ("vo", "other", "manual"):
        tracker.set_sama_lang_pref(pref)
        assert tracker.get_sama_lang_pref() == pref


def test_sama_lang_pref_invalid_value_falls_back_to_manual(tracker):
    tracker.data["sama_lang_pref"] = "bogus"
    assert tracker.get_sama_lang_pref() == "manual"
