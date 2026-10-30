from __future__ import annotations

import pytest

from autoflix_cli.cli_utils import (
    clean_title,
    print_error,
    _truncate,
    _is_disabled,
    _visible_len,
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


def test_visible_len_ignores_ansi_codes():
    assert _visible_len("\x1b[1mhello\x1b[0m") == 5


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


def test_select_from_list_uses_fzf_backend(monkeypatch, capsys):
    import autoflix_cli.cli_utils as cli_utils

    seen = {}

    def fake_fzf(options, prompt, default_index, *, is_disabled):
        seen["prompt"] = prompt
        seen["is_disabled"] = is_disabled
        return 2  # "← Back"

    monkeypatch.setattr(cli_utils, "_is_interactive", lambda: True)
    monkeypatch.setattr(cli_utils, "fzf_enabled", lambda: True)
    monkeypatch.setattr(cli_utils, "select_with_fzf", fake_fzf)
    assert (
        cli_utils.select_from_list(["mpv", "vlc", "← Back"], "Pick:") == 2
    )
    assert seen["prompt"] == "Pick:"
    assert capsys.readouterr().out.strip() == "❯ Pick: ← Back"


def test_select_from_list_falls_back_when_fzf_fails(monkeypatch):
    import autoflix_cli.cli_utils as cli_utils
    from autoflix_cli.fzf_menu import FzfError

    def broken_fzf(*args, **kwargs):
        raise FzfError("fzf cannot run")

    monkeypatch.setattr(cli_utils, "_is_interactive", lambda: False)
    monkeypatch.setattr(cli_utils, "fzf_enabled", lambda: True)
    monkeypatch.setattr(cli_utils, "select_with_fzf", broken_fzf)
    monkeypatch.setattr(
        cli_utils, "_fallback_select", lambda opts, prompt, di: 99
    )
    assert cli_utils.select_from_list(["mpv", "vlc", "↩ Back"], "Pick:") == 99


def test_select_from_list_skips_fzf_when_disabled(monkeypatch):
    import autoflix_cli.cli_utils as cli_utils

    def fail_fzf(*args, **kwargs):
        pytest.fail("fzf backend must not run")

    monkeypatch.setattr(cli_utils, "_is_interactive", lambda: False)
    monkeypatch.setattr(cli_utils, "fzf_enabled", lambda: False)
    monkeypatch.setattr(cli_utils, "select_with_fzf", fail_fzf)
    monkeypatch.setattr(cli_utils, "_fallback_select", lambda opts, prompt, di: 1)
    assert cli_utils.select_from_list(["mpv", "vlc"], "Pick:") == 1
