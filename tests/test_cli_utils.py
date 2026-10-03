from autoflix_cli.cli_utils import (
    clean_title,
    _truncate,
    _is_disabled,
    _visible_len,
)


def test_clean_title_removes_season_markers():
    assert clean_title("One Piece Season 4") == "One Piece"
    assert clean_title("Show S02") == "Show"
    assert clean_title("Movie Part 1") == "Movie"
    assert clean_title("Anime 2nd Season") == "Anime"


def test_clean_title_keeps_plain_titles():
    assert clean_title("Some Regular Title") == "Some Regular Title"


def test_truncate_short_text_untouched():
    assert _truncate("hello", 10) == "hello"


def test_truncate_long_text_keeps_one_line():
    assert _truncate("a" * 20, 10) == "a" * 9 + "…"
    assert _truncate("line1\nline2", 10) == "line1 lin…"


def test_is_disabled_detects_separators():
    assert _is_disabled("")
    assert _is_disabled("── Unsupported players ──")
    assert _is_disabled("── test ──")
    assert not _is_disabled("mpv")


def test_visible_len_ignores_ansi_codes():
    assert _visible_len("\x1b[1mhello\x1b[0m") == 5
