"""Tests for Roman numeral season detection in the AniList handler."""
import pytest
from autoflix_cli.handlers.anilist import _parse_roman, _ROMAN_TO_INT, _TRAILING_ROMAN


# ---------------------------------------------------------------------------
# _parse_roman
# ---------------------------------------------------------------------------

def test_parse_roman_detects_trailing_ii():
    assert _parse_roman("From Old Country Bumpkin to Master Swordsman II") == 2


def test_parse_roman_detects_trailing_iii():
    assert _parse_roman("My Hero Academia III") == 3


def test_parse_roman_detects_trailing_iv():
    assert _parse_roman("Some Anime IV") == 4


def test_parse_roman_detects_trailing_i():
    assert _parse_roman("Some Show I") == 1


def test_parse_roman_case_insensitive():
    assert _parse_roman("Title ii") == 2
    assert _parse_roman("Title Iv") == 4


def test_parse_roman_ignores_mid_word_roman():
    # Roman characters that aren't a standalone trailing token must not match
    assert _parse_roman("Title IIX") is None


def test_parse_roman_returns_none_for_plain_title():
    assert _parse_roman("One Piece") is None
    assert _parse_roman("Attack on Titan") is None
    assert _parse_roman("The 100") is None


def test_parse_roman_returns_none_for_season_word():
    # "Season 2" should not be caught by the Roman numeral parser
    assert _parse_roman("My Show Season 2") is None


# ---------------------------------------------------------------------------
# _auto_select_season integration (monkeypatched select)
# ---------------------------------------------------------------------------

class _FakeSeason:
    def __init__(self, title):
        self.title = title


def test_auto_select_season_roman_ii_picks_second_season(monkeypatch):
    """'Title II' on AniList should auto-suggest the provider's season 2."""
    from autoflix_cli.handlers import anilist

    seasons = [_FakeSeason("Saison 1"), _FakeSeason("Saison 2"), _FakeSeason("Saison 3")]
    chosen = []

    monkeypatch.setattr(
        anilist, "select_from_list",
        lambda options, prompt, default_index=0, **kw: chosen.append(default_index) or default_index,
    )
    monkeypatch.setattr(anilist, "print_info", lambda *a, **kw: None)

    result = anilist._auto_select_season(
        seasons,
        media_title="From Old Country Bumpkin to Master Swordsman II",
        romaji_title=None,
    )

    assert chosen[0] == 1          # index 1 = "Saison 2"
    assert result is seasons[1]


def test_auto_select_season_roman_iii_picks_third_season(monkeypatch):
    from autoflix_cli.handlers import anilist

    seasons = [_FakeSeason("Saison 1"), _FakeSeason("Saison 2"), _FakeSeason("Saison 3")]
    chosen = []

    monkeypatch.setattr(
        anilist, "select_from_list",
        lambda options, prompt, default_index=0, **kw: chosen.append(default_index) or default_index,
    )
    monkeypatch.setattr(anilist, "print_info", lambda *a, **kw: None)

    result = anilist._auto_select_season(
        seasons,
        media_title="My Hero Academia III",
        romaji_title=None,
    )

    assert chosen[0] == 2
    assert result is seasons[2]


def test_auto_select_season_provider_roman_title(monkeypatch):
    """Provider seasons labelled with Roman numerals are also matched."""
    from autoflix_cli.handlers import anilist

    seasons = [_FakeSeason("Title I"), _FakeSeason("Title II"), _FakeSeason("Title III")]
    chosen = []

    monkeypatch.setattr(
        anilist, "select_from_list",
        lambda options, prompt, default_index=0, **kw: chosen.append(default_index) or default_index,
    )
    monkeypatch.setattr(anilist, "print_info", lambda *a, **kw: None)

    result = anilist._auto_select_season(
        seasons,
        media_title="Title II",
        romaji_title=None,
    )

    assert chosen[0] == 1
    assert result is seasons[1]
