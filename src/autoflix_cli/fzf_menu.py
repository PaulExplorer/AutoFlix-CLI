from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from typing import Callable, Sequence

__all__ = [
    "FzfError",
    "fzf_enabled",
    "reset_cache",
    "select_with_fzf",
]


class FzfError(Exception):
    """Raised when fzf cannot be used: caller must fall back to the
    built-in menu. Never raised for an actual user cancel (Esc / Ctrl-C
    are handled according to the menu contract)."""


_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
_DIM = "\x1b[90m"
_RESET = "\x1b[0m"

_available: bool | None = None


def _is_interactive() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


def fzf_enabled() -> bool:
    """Return True when fzf can drive the menus on this terminal."""
    global _available
    if _available is None:
        _available = bool(
            _is_interactive()
            and os.environ.get("TERM") != "dumb"
            and shutil.which("fzf")
        )
    return _available


def reset_cache() -> None:
    """Forget the cached availability check (used by tests)."""
    global _available
    _available = None


def _flatten(label: str) -> str:
    """Reduce a label to a single line for the fzf feed."""
    return label.replace("\r", " ").replace("\n", " ")


def _display_line(label: str, off: bool) -> str:
    """Build one fed line; disabled rows are rendered dimmed via ANSI."""
    flat = _flatten(label)
    return f"{_DIM}{flat}{_RESET}" if off else flat


def _strip_ansi(line: str) -> str:
    return _ANSI_RE.sub("", line)


def _map_choice(
    chosen: str, items: Sequence[str], is_off: Sequence[bool]
) -> int | None:
    """Map the line reported by fzf back to the original options index.

    The line may carry ANSI codes (dimmed rows), so both sides are
    stripped before comparison. Duplicate labels resolve to their first
    occurrence in feed order (visually identical rows are ambiguous for
    any stdin/stdout-based picker anyway).

    Returns:
        The original index, or ``None`` when the row is disabled
        (separator): the caller re-opens the menu in that case.
    """
    chosen_flat = _strip_ansi(chosen)
    for i, item in enumerate(items):
        if _flatten(item) == chosen_flat:
            return None if is_off[i] else i
    raise FzfError(f"fzf returned an unknown row: {chosen_flat!r}")


def _last_selectable(is_off: Sequence[bool]) -> int:
    """Index of the last selectable row (codebase convention: the final
    option is always the safe Back / Cancel choice)."""
    for i in range(len(is_off) - 1, -1, -1):
        if not is_off[i]:
            return i
    return 0


_FZF_ARGS = [
    "fzf",
    # Disabled (separator) rows are dimmed through ANSI codes.
    "--ansi",
    "--no-multi",
    "--reverse",
    "--header-first",
    "--inline-info",
    "--pointer", "❯",
    "--expect", "esc,ctrl-d",
]


def select_with_fzf(
    options: Sequence[str],
    prompt: str,
    default_index: int,
    *,
    is_disabled: Callable[[str], bool],
) -> int:
    """Show the menu with fzf and return the chosen index in ``options``.

    Semantics match :func:`autoflix_cli.cli_utils.select_from_list`:
    - Esc returns the last selectable entry (the safe Back / Cancel row).
    - Ctrl-C / Ctrl-D raise ``KeyboardInterrupt``.
    - Picking a disabled (separator) row re-opens the menu, like the
      built-in loop ignoring Enter on those rows.
    - Anything that prevents fzf from running raises :class:`FzfError`
      so the caller can fall back to the built-in menu.
    """
    if not fzf_enabled():
        raise FzfError("fzf is not available")

    items = list(options)
    is_off = [is_disabled(o) for o in items]
    feed = "\n".join(_display_line(o, off) for o, off in zip(items, is_off)) + "\n"

    args = _FZF_ARGS + ["--header", prompt]

    env = dict(os.environ)
    # User fzf config must not change what we parse (e.g. --expect, --header).
    env["FZF_DEFAULT_OPTS"] = ""

    # Re-open the menu if a non-selectable row was picked, mirroring the
    # built-in behaviour where Enter on a separator is ignored.
    for _ in range(3):
        try:
            proc = subprocess.run(
                args,
                input=feed,
                capture_output=True,
                text=True,
                env=env,
            )
        except FileNotFoundError:
            raise FzfError("fzf disappeared from PATH")
        if proc.returncode == 130:
            # Ctrl-C aborts fzf: real interruption, not a menu cancel.
            raise KeyboardInterrupt("Menu cancelled by user")
        if proc.returncode != 0:
            raise FzfError(
                f"fzf exited with code {proc.returncode}: "
                f"{(proc.stderr or '').strip()}"
            )

        lines = proc.stdout.split("\n", 1)
        pressed = lines[0].strip()
        selection = lines[1] if len(lines) > 1 else ""
        chosen = "\n".join(selection.splitlines()[:1]).strip("\n")

        if pressed == "esc":
            return _last_selectable(is_off)
        if pressed == "ctrl-d":
            raise KeyboardInterrupt("Menu cancelled by user")

        # Enter: "pressed" is empty. No selection (e.g. Enter while no
        # match) falls back to the safe Back row like an Esc press.
        if not chosen:
            return _last_selectable(is_off)
        index = _map_choice(chosen, items, is_off)
        if index is None:
            continue
        return index

    raise FzfError("fzf did not return a selectable row")
