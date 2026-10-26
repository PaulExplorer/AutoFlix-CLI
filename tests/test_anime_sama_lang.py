import pytest

from autoflix_cli.tracker import tracker
from autoflix_cli.handlers.anime_sama import pick_language_auto, _select_language


@pytest.fixture
def no_output(monkeypatch):
    """Silence the info message printed when a language is auto-picked."""
    monkeypatch.setattr(
        "autoflix_cli.handlers.anime_sama.print_info", lambda *a, **k: None
    )


def test_pref_vo_picks_vostfr(monkeypatch):
    monkeypatch.setattr(tracker, "get_sama_lang_pref", lambda: "vo")

    assert pick_language_auto(["vostfr", "vf"]) == "vostfr"
    assert pick_language_auto(["vostfr"]) == "vostfr"


def test_pref_vo_falls_back_when_missing(monkeypatch):
    monkeypatch.setattr(tracker, "get_sama_lang_pref", lambda: "vo")

    assert pick_language_auto(["vf", "vf1"]) is None


def test_pref_other_picks_non_vo_when_two_choices(monkeypatch):
    monkeypatch.setattr(tracker, "get_sama_lang_pref", lambda: "other")

    assert pick_language_auto(["vostfr", "vf"]) == "vf"
    assert pick_language_auto(["vf", "vostfr"]) == "vf"


def test_pref_other_does_nothing_with_more_choices(monkeypatch):
    monkeypatch.setattr(tracker, "get_sama_lang_pref", lambda: "other")

    assert pick_language_auto(["vostfr", "vf", "vf1"]) is None
    assert pick_language_auto(["vf", "vf1"]) is None


def test_pref_manual_does_nothing(monkeypatch):
    monkeypatch.setattr(tracker, "get_sama_lang_pref", lambda: "manual")

    assert pick_language_auto(["vostfr", "vf"]) is None
    assert pick_language_auto(["vostfr"]) is None


def test_default_pref_is_manual(monkeypatch):
    monkeypatch.setattr(tracker, "get_sama_lang_pref", lambda: "manual")

    assert pick_language_auto(["vostfr", "vf"]) is None


def test_select_language_single_option_auto_picked(no_output):
    assert _select_language(["vf"]) == "vf"


def test_select_language_returns_none_on_back(
    monkeypatch, no_output, capsys
):
    monkeypatch.setattr(tracker, "get_sama_lang_pref", lambda: "manual")
    monkeypatch.setattr(
        "autoflix_cli.handlers.anime_sama.select_from_list",
        lambda options, prompt: len(options) - 1,
    )

    assert _select_language(["vostfr", "vf"]) is None


def test_select_language_manual_choice(
    monkeypatch, no_output
):
    monkeypatch.setattr(tracker, "get_sama_lang_pref", lambda: "manual")
    monkeypatch.setattr(
        "autoflix_cli.handlers.anime_sama.select_from_list",
        lambda options, prompt: 1,
    )

    assert _select_language(["vostfr", "vf"]) == "vf"
