from __future__ import annotations

import pytest

from autoflix_cli.fzf_menu import (
    FzfError,
    _display_line,
    _flatten,
    _last_selectable,
    _map_choice,
    _strip_ansi,
    fzf_enabled,
    reset_cache,
)


@pytest.fixture(autouse=True)
def _fresh_cache():
    reset_cache()
    yield
    reset_cache()


def _states(items, disabled_pred=None):
    off = []
    for o in list(items):
        off.append(bool(disabled_pred(o)) if disabled_pred else o == "")
    return off


def test_flatten_removes_line_breaks():
    assert _flatten("line1\nline2\r\nmore") == "line1 line2  more"


def test_display_line_dims_disabled_rows():
    assert _display_line("mpv", False) == "mpv"
    dimmed = _display_line("── Unsupported ──", True)
    assert dimmed.startswith("\x1b[90m")
    assert dimmed.endswith("\x1b[0m")


def test_strip_ansi_removes_style_codes():
    assert _strip_ansi("\x1b[90m── x ──\x1b[0m") == "── x ──"
    assert _strip_ansi("plain") == "plain"


def test_map_choice_matches_selectable_row():
    items = ["mpv", "vlc", "── Unsupported ──", "mpv (proxy)"]
    is_off = [False, False, True, False]
    assert _map_choice("vlc", items, is_off) == 1


def test_map_choice_unwraps_ansi_from_dimmed_line():
    items = ["mpv", "── sep ──"]
    is_off = [False, True]
    chosen = _display_line("── sep ──", True)
    assert _map_choice(chosen, items, is_off) is None


def test_map_choice_unknown_row_raises():
    with pytest.raises(FzfError):
        _map_choice("ghost", ["mpv"], [False])


def test_last_selectable_follows_back_convention():
    assert _last_selectable([False, False, False]) == 2
    # Last row is a separator: skip it.
    assert _last_selectable([False, True]) == 0
    assert _last_selectable([True, False, True]) == 1


def test_fzf_enabled_false_without_tty(monkeypatch):
    import autoflix_cli.fzf_menu as fzf_menu

    monkeypatch.setattr(fzf_menu.sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr(fzf_menu.sys.stdout, "isatty", lambda: True)
    assert fzf_enabled() is False
    reset_cache()
    monkeypatch.setattr(fzf_menu.shutil, "which", lambda name: None)
    monkeypatch.setattr(fzf_menu.sys.stdin, "isatty", lambda: True)
    assert fzf_enabled() is False


class _Proc:
    def __init__(self, code, out, err=""):
        self.returncode = code
        self.stdout = out
        self.stderr = err


def _fake_run(monkeypatch, results):
    """Patch subprocess.run to pop fake results (code, out, err)."""
    import autoflix_cli.fzf_menu as fzf_menu

    calls = []
    results = list(results)

    def run(args, **kwargs):
        calls.append((args, kwargs))
        code, out, err = results.pop(0)
        return _Proc(code, out, err)

    monkeypatch.setattr(fzf_menu.subprocess, "run", run)
    return calls


def test_select_with_fzf_returns_original_index(monkeypatch):
    import autoflix_cli.fzf_menu as fzf_menu

    calls = _fake_run(monkeypatch, [(0, "\nmpv\n", "")])
    monkeypatch.setattr(fzf_menu, "fzf_enabled", lambda: True)
    assert (
        fzf_menu.select_with_fzf(["mpv", "vlc"], "Pick:", 0, is_disabled=lambda o: False)
        == 0
    )
    # The choices are fed on stdin, the prompt goes through --header.
    args, kwargs = calls[0]
    assert "--header" in args
    assert args[args.index("--header") + 1] == "Pick:"
    assert kwargs["input"] == "mpv\nvlc\n"


def test_select_with_fzf_esc_returns_last_selectable(monkeypatch):
    import autoflix_cli.fzf_menu as fzf_menu

    _fake_run(monkeypatch, [(0, "esc\n", "")])
    monkeypatch.setattr(fzf_menu, "fzf_enabled", lambda: True)
    assert (
        fzf_menu.select_with_fzf(
            ["mpv", "vlc", "← Back"],
            "Pick:",
            0,
            is_disabled=lambda o: False,
        )
        == 2
    )


def test_select_with_fzf_ctrl_d_raises(monkeypatch):
    import autoflix_cli.fzf_menu as fzf_menu

    _fake_run(monkeypatch, [(0, "ctrl-d\n", "")])
    monkeypatch.setattr(fzf_menu, "fzf_enabled", lambda: True)
    with pytest.raises(KeyboardInterrupt):
        fzf_menu.select_with_fzf(["mpv"], "Pick:", 0, is_disabled=lambda o: False)


def test_select_with_fzf_abort_exits_like_ctrl_c(monkeypatch):
    import autoflix_cli.fzf_menu as fzf_menu

    _fake_run(monkeypatch, [(130, "", "")])
    monkeypatch.setattr(fzf_menu, "fzf_enabled", lambda: True)
    with pytest.raises(KeyboardInterrupt):
        fzf_menu.select_with_fzf(["mpv"], "Pick:", 0, is_disabled=lambda o: False)


def test_select_with_fzf_reopens_on_disabled_row(monkeypatch):
    import autoflix_cli.fzf_menu as fzf_menu

    sep = _display_line("── sep ──", True)  # fzf echoes the fed line back
    calls = _fake_run(monkeypatch, [(0, f"\n{sep}\n", ""), (0, "\nmpv\n", "")])
    monkeypatch.setattr(fzf_menu, "fzf_enabled", lambda: True)
    assert (
        fzf_menu.select_with_fzf(
            ["mpv", "── sep ──"],
            "Pick:",
            0,
            is_disabled=lambda o: o.startswith("──"),
        )
        == 0
    )
    assert len(calls) == 2  # menu re-opened once, like the built-in loop


def test_select_with_fzf_crash_raises_fzf_error(monkeypatch):
    import autoflix_cli.fzf_menu as fzf_menu

    _fake_run(monkeypatch, [(42, "", "boom")])
    monkeypatch.setattr(fzf_menu, "fzf_enabled", lambda: True)
    with pytest.raises(FzfError):
        fzf_menu.select_with_fzf(["mpv"], "Pick:", 0, is_disabled=lambda o: False)


def test_select_with_fzf_unavailable_raises_fzf_error(monkeypatch):
    import autoflix_cli.fzf_menu as fzf_menu

    monkeypatch.setattr(fzf_menu, "fzf_enabled", lambda: False)
    with pytest.raises(FzfError):
        fzf_menu.select_with_fzf(["mpv"], "Pick:", 0, is_disabled=lambda o: False)
