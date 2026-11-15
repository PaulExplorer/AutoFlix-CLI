from autoflix_cli import cli_utils
from autoflix_cli.cli_utils import (
    _is_disabled,
    _refresh_cursor,
    _truncate,
    clean_title,
    print_error,
    select_from_list,
    supports_live_refresh,
)


def test_clean_title_removes_season_markers():
    assert clean_title("One Piece Season 4") == "One Piece"
    assert clean_title("Show S02") == "Show"
    assert clean_title("Movie Part 1") == "Movie"
    assert clean_title("Anime 2nd Season") == "Anime"


def test_clean_title_strips_trailing_roman_numerals():
    assert clean_title("From Old Country Bumpkin to Master Swordsman II") == "From Old Country Bumpkin to Master Swordsman"
    assert clean_title("My Hero Academia III") == "My Hero Academia"
    assert clean_title("Some Anime IV") == "Some Anime"
    # Season I (= 1) should also be stripped
    assert clean_title("Some Show I") == "Some Show"
    # Plain title with a roman numeral embedded mid-word must NOT be stripped
    assert clean_title("Title IIX") == "Title IIX"


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
def test_print_error_displays_message_and_issue_link(capsys):
    print_error("Test failure message")
    captured = capsys.readouterr().out
    assert "Test failure message" in captured
    assert "https://github.com/PaulExplorer/AutoFlix-CLI/issues" in captured
    assert "français" in captured


def test_print_error_without_issue_link(capsys):
    print_error("Test failure message", show_issue=False)
    captured = capsys.readouterr().out
    assert "Test failure message" in captured
    assert "https://github.com/PaulExplorer/AutoFlix-CLI/issues" not in captured


# --- live refresh -----------------------------------------------------------


def test_refresh_cursor_follows_the_selected_label():
    # A source appended above the highlight must not steal the cursor.
    assert _refresh_cursor(["new", "a", "b"], [0, 1, 2], 1, "b") == 2
    # Same row, same place: nothing to do.
    assert _refresh_cursor(["a", "b"], [0, 1], 1, "b") == 1
    # A removed row falls back to the same position, clamped.
    assert _refresh_cursor(["a", "b"], [0, 1], 9, "gone") == 1
    assert _refresh_cursor([], [], 0, "a") == 0


def _fake_keys(monkeypatch, keys):
    """Drive ``select_from_list`` without a terminal."""
    pending = list(keys)

    def read_key(timeout=None):
        return pending.pop(0) if pending else "\r"

    monkeypatch.setattr(cli_utils, "_is_interactive", lambda: True)
    monkeypatch.setattr(cli_utils, "_read_key", read_key)


def test_menu_refreshes_itself_while_waiting_for_a_key(monkeypatch):
    options = ["a", "b", "← Back"]
    frames = [["new", "a", "b", "← Back"]]
    calls = []

    def refresher():
        calls.append(len(frames))
        return (frames.pop(0), "pick") if frames else None

    _fake_keys(monkeypatch, [cli_utils.readchar.key.DOWN, None, "\r"])

    chosen = select_from_list(options, "pick", refresher=refresher)

    assert calls  # the menu asked for a new frame without a keypress
    # The highlight was on "b"; the new row was inserted above it, so the
    # index must follow the label, not the position. It indexes the list the
    # refresher returned last, which is what the caller keeps on its side.
    assert chosen == 2
    assert ["new", "a", "b", "← Back"][chosen] == "b"


def test_menu_keeps_its_rows_when_the_refresher_fails(monkeypatch):
    def refresher():
        raise RuntimeError("boom")

    _fake_keys(monkeypatch, [None, None, "\r"])

    assert select_from_list(["a", "b"], "pick", refresher=refresher) == 0


def test_menu_never_empties_itself(monkeypatch):
    _fake_keys(monkeypatch, [None, "\r"])

    assert select_from_list(["a"], "pick", refresher=lambda: ([], "pick")) == 0


def test_live_refresh_needs_a_terminal(monkeypatch):
    monkeypatch.setattr(cli_utils, "_is_interactive", lambda: False)
    assert supports_live_refresh() is False
    monkeypatch.setattr(cli_utils, "_is_interactive", lambda: True)
    monkeypatch.setattr(cli_utils.os, "name", "nt")
    assert supports_live_refresh() is False
