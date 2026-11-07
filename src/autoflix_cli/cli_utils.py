from __future__ import annotations

import os
import re
import shutil
import sys
from contextlib import contextmanager
from typing import Callable, Sequence

import readchar
from rich.cells import cell_len
from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.text import Text

# Shared console for all static (non-interactive) output.
# ``highlight=False`` avoids mangling URLs with Rich highlighting.
console = Console(highlight=False)

__all__ = [
    "clean_title",
    "clear_screen",
    "confirm",
    "console",
    "get_user_input",
    "pause",
    "print_banner",
    "print_divider",
    "print_error",
    "print_header",
    "print_info",
    "print_step",
    "print_success",
    "print_warning",
    "select_from_list",
    "status",
]

_HIDE_CURSOR = "\x1b[?25l"
_SHOW_CURSOR = "\x1b[?25h"

_MAX_VISIBLE_ROWS = 20
_MIN_VISIBLE_ROWS = 5


# ---------------------------------------------------------------------------
# Static output helpers
# ---------------------------------------------------------------------------

def clear_screen() -> None:
    """Clear the terminal screen without spawning a subprocess."""
    try:
        console.clear()
    except Exception:
        # Fallback for exotic terminals where Rich clear fails.
        sys.stdout.write("\x1b[2J\x1b[H")
        sys.stdout.flush()


def print_banner(subtitle: str | None = None) -> None:
    """Print a compact application banner."""
    title = Text("AutoFlix", style="bold bright_cyan")
    title.append(" CLI", style="bold white")
    body = Text("Watch movies, series and anime from your terminal.", style="dim")
    if subtitle:
        body.append(f"\n{subtitle}", style="cyan")
    console.print(
        Panel(
            Text.assemble(title, "\n", body),
            border_style="cyan",
            padding=(0, 2),
            expand=False,
        )
    )


def print_header(text: str, subtitle: str | None = None) -> None:
    """Print a slim section header.

    Args:
        text: Main header text.
        subtitle: Optional dimmer second line.
    """
    content = Text(text, style="bold white", justify="center")
    if subtitle:
        content.append(f"\n{subtitle}", style="dim cyan")
    console.print()
    console.print(
        Panel(
            content,
            style="cyan",
            border_style="cyan",
            padding=(0, 2),
        )
    )


def print_success(message: str) -> None:
    """Print a success message."""
    console.print(f"[green]✓[/green] {message}")


def print_error(message: str, show_issue: bool = True) -> None:
    """Print an error message."""
    console.print(f"[red]✗[/red] {message}")
    if show_issue:
        console.print(
            "[dim]Please open an issue at: [cyan underline]https://github.com/PaulExplorer/AutoFlix-CLI/issues[/cyan underline]\n"
            "(Si vous parlez français, vous pouvez aussi l'ouvrir en français.)[/dim]"
        )


def print_info(message: str) -> None:
    """Print an info message."""
    console.print(f"[cyan]›[/cyan] {message}")


def print_warning(message: str) -> None:
    """Print a warning message."""
    console.print(f"[yellow]![/yellow] {message}")


def print_step(message: str) -> None:
    """Print a neutral step/progress message."""
    console.print(f"[dim]•[/dim] {message}")


def print_divider() -> None:
    """Print a subtle horizontal divider."""
    console.print("[dim]" + "─" * 40 + "[/dim]")


@contextmanager
def status(message: str):
    """Show a lightweight spinner while a blocking task runs.

    Example:
        with status("Resolving stream..."):
            stream_url = resolve(url)
    """
    with console.status(f"[cyan]{message}[/cyan]", spinner="dots"):
        yield


# ---------------------------------------------------------------------------
# Input helpers
# ---------------------------------------------------------------------------

def _input_prefix(prompt: str, default: str | None = None) -> Text:
    """Build the styled prompt printed before the editable buffer."""
    prefix = Text()
    prefix.append("❯ ", style="bold cyan")
    prefix.append(prompt, style="bold cyan")
    if default:
        prefix.append(f" ({default})", style="dim")
    prefix.append(" [Esc cancels]", style="dim")
    prefix.append(": ")
    return prefix


def _redraw_line(prefix: Text, buffer: str) -> None:
    """Redraw prompt + input buffer, always within one physical line.

    The prefix is truncated first on very narrow terminals, then the
    buffer keeps its tail (newest characters) visible. Keeping the whole
    line inside one physical row is what makes the ``\\r`` + clear
    escape sequences reliable; a soft-wrapped line used to duplicate the
    prompt on every keypress.
    """
    width = max(20, shutil.get_terminal_size(fallback=(80, 24)).columns)
    text = prefix.copy()
    # Keep room for ": " and a few visible characters of the buffer even
    # on very narrow terminals.
    max_prefix = max(8, width - 10)
    truncated = text.cell_len > max_prefix
    if truncated:
        text.truncate(max_width=max_prefix, overflow="ellipsis", pad=False)
        text.append(": ")
    room = max(2, width - 1 - text.cell_len)
    display = buffer.replace("\t", " ")
    # Cell-aware tail cut so wide glyphs (emoji...) cannot overshoot.
    if cell_len(display) > room:
        cut = len(display)
        used = 1  # room for the ellipsis
        for i in range(len(display) - 1, -1, -1):
            if used + cell_len(display[i]) > room:
                break
            used += cell_len(display[i])
            cut = i
        display = "…" + display[cut:]
    text.append(display)
    out = sys.stdout
    out.write("\r\x1b[2K")
    console.print(text, end="", soft_wrap=True)
    out.flush()


def _read_line_posix(prefix: Text) -> str | None:
    """Read one line in cbreak mode. Returns None on Esc/Ctrl-C/Ctrl-D/EOF.

    Minimal append-only editor: printable characters (including pasted
    text and UTF-8), Backspace, Ctrl-U (clear line), Ctrl-W (delete
    last word), Enter submits. Arrow keys are ignored (no mid-line
    cursor, by design: keeps this lightweight and predictable).

    Args:
        prefix: Styled prompt (Rich Text) reprinted on every redraw so
            typing never erases it.
    """
    buf: list[str] = []
    while True:
        try:
            key = _read_key_posix()
        except KeyboardInterrupt:
            # Real Ctrl-C signal during the prompt: cancel the prompt,
            # do not quit the app (quitting stays available in menus).
            sys.stdout.write("\n")
            sys.stdout.flush()
            return None
        if key in ("\r", "\n"):
            sys.stdout.write("\n")
            sys.stdout.flush()
            return "".join(buf)
        if key == "\x1b":  # Esc cancels.
            sys.stdout.write("\n")
            sys.stdout.flush()
            return None
        if key in ("\x04", "\x1a"):  # Ctrl-D / Ctrl-Z: cancel.
            sys.stdout.write("\n")
            sys.stdout.flush()
            return None
        if key in ("\x7f", "\x08"):  # Backspace.
            if buf:
                buf.pop()
                _redraw_line(prefix, "".join(buf))
            continue
        if key == "\x15":  # Ctrl-U: clear line.
            if buf:
                buf.clear()
                _redraw_line(prefix, "")
            continue
        if key == "\x17":  # Ctrl-W: delete last word.
            if buf:
                text = "".join(buf).rstrip()
                idx = max(text.rfind(" "), text.rfind("\t"))
                buf = list(text[: idx + 1] if idx != -1 else "")
                _redraw_line(prefix, "".join(buf))
            continue
        if len(key) == 1 and key.isprintable() and key != "\t":
            buf.append(key)
            _redraw_line(prefix, "".join(buf))
        # Anything else (arrows, function keys...): ignore.


def _read_line_windows(prefix: Text) -> str | None:
    """Read one line on Windows. Returns None on Esc/Ctrl-C/Ctrl-Z."""
    import msvcrt

    buf: list[str] = []
    while True:
        try:
            key = msvcrt.getwch()
        except KeyboardInterrupt:
            print()
            return None
        if key in ("\r", "\n"):
            print()
            return "".join(buf)
        if key in ("\x1b", "\x03", "\x1a"):  # Esc / Ctrl-C / Ctrl-Z.
            print()
            return None
        if key in ("\x00", "\xe0"):  # Arrow / function key prefix.
            try:
                msvcrt.getwch()  # Consume the second code, ignore the key.
            except (KeyboardInterrupt, IOError):
                print()
                return None
            continue
        if key in ("\x08", "\x7f"):  # Backspace.
            if buf:
                buf.pop()
                _redraw_line(prefix, "".join(buf))
            continue
        if key == "\x15":  # Ctrl-U: clear line.
            if buf:
                buf.clear()
                _redraw_line(prefix, "")
            continue
        if len(key) == 1 and key.isprintable() and key != "\t":
            buf.append(key)
            _redraw_line(prefix, "".join(buf))
        # Anything else: ignore.


def _read_line(prefix: Text) -> str | None:
    """Read one line in raw mode using ``prefix`` as the styled prompt.

    Args:
        prefix: Styled prompt (Rich Text) reprinted on every redraw.

    Returns:
        The typed line, or ``None`` when cancelled (Esc / Ctrl-C / EOF).
    """
    if os.name == "nt":
        return _read_line_windows(prefix)
    return _read_line_posix(prefix)


def _is_interactive() -> bool:
    """Return True when key-aware prompts (menus, line editor) can run."""
    return (
        sys.stdin.isatty()
        and sys.stdout.isatty()
        and os.environ.get("TERM") != "dumb"
    )


def get_user_input(prompt: str, default: str | None = None) -> str | None:
    """Ask for a line of text with a styled prompt.

    On an interactive terminal, Esc (or Ctrl-C / Ctrl-D) cancels the
    prompt and ``None`` is returned so the caller can go back instead
    of crashing. An empty submission returns ``default`` (or ``""``).

    Args:
        prompt: Text shown to the user.
        default: Value returned when the user submits an empty line.

    Returns:
        The stripped user input, ``default`` on empty input, or ``None``
        when the user cancels (interactive terminal only).
    """
    suffix = f" [dim]({default})[/dim]" if default else ""
    if _is_interactive():
        prefix = _input_prefix(prompt, default)
        sys.stdout.write("\n")
        sys.stdout.flush()
        _redraw_line(prefix, "")
        try:
            value = _read_line(prefix)
        except (EOFError, KeyboardInterrupt):
            value = None
        if value is None:
            console.print("[dim](cancelled)[/dim]")
            return None
        value = value.strip()
        return value or (default or "")
    try:
        console.print(f"\n[bold cyan]❯ {prompt}[/bold cyan]{suffix}: ", end="")
        value = input().strip()
    except (EOFError, KeyboardInterrupt):
        console.print()
        raise KeyboardInterrupt("Input cancelled by user") from None
    return value or (default or "")


def confirm(prompt: str, default: bool = True) -> bool:
    """Ask a yes/no question.

    Args:
        prompt: Question text.
        default: Value used on empty input or when cancelled.

    Returns:
        True for yes, False for no.
    """
    hint = "Y/n" if default else "y/N"
    if _is_interactive():
        prefix = Text()
        prefix.append("❯ ", style="bold cyan")
        prefix.append(prompt, style="bold cyan")
        prefix.append(f" [{hint}]", style="dim")
        prefix.append(" [Esc cancels]", style="dim")
        prefix.append(": ")
        _redraw_line(prefix, "")
        try:
            value = _read_line(prefix)
        except (EOFError, KeyboardInterrupt):
            value = None
        if value is None:
            console.print("[dim](cancelled)[/dim]")
            return default
        value = value.strip().lower()
        if not value:
            return default
        return value in ("y", "yes", "o", "oui")
    try:
        console.print(f"[bold cyan]❯ {prompt}[/bold cyan] [dim][{hint}][/dim]: ", end="")
        value = input().strip().lower()
    except (EOFError, KeyboardInterrupt):
        console.print()
        raise KeyboardInterrupt("Input cancelled by user") from None
    if not value:
        return default
    return value in ("y", "yes", "o", "oui")


def pause(message: str = "Press Enter to continue...") -> None:
    """Wait for the user to press Enter."""
    try:
        console.print(f"\n[dim]{message}[/dim]", end="")
        input()
    except (EOFError, KeyboardInterrupt):
        console.print()
        raise KeyboardInterrupt("Paused action cancelled by user") from None


# ---------------------------------------------------------------------------
# Interactive selection menu
# ---------------------------------------------------------------------------

def _is_disabled(option: str) -> bool:
    """Return True for separator / non-selectable rows.

    Some callers insert visual separators such as ``""`` or
    ``"── Unsupported players ──"``. These rows are displayed dimmed
    and are skipped during navigation.
    """
    stripped = option.strip()
    return (
        stripped == ""
        or stripped.startswith("──")
        or stripped.startswith("─" * 3)
        or stripped.startswith("--")
    )


def _truncate(text: str, width: int) -> str:
    """Truncate a row to the given display width, keeping one line only."""
    single_line = text.replace("\n", " ").replace("\r", " ")
    t = Text(single_line)
    # Text.truncate uses Rich's cell_len: emoji / double-width glyphs are
    # measured the way terminals actually display them.
    if t.cell_len > width:
        t.truncate(max_width=width, overflow="ellipsis", pad=False)
    return t.plain


def _fallback_select(options: Sequence[str], prompt: str, default_index: int) -> int:
    """Numbered fallback menu used when no interactive TTY is available."""
    console.print(f"\n[bold cyan]❯ {prompt}[/bold cyan]")
    for i, option in enumerate(options):
        marker = "›" if i == default_index else " "
        console.print(f"  [dim]{marker} {i + 1}.[/dim] {option}")
    while True:
        try:
            raw = input(f"Choice [1-{len(options)}] (default {default_index + 1}): ").strip()
        except (EOFError, KeyboardInterrupt):
            console.print()
            raise KeyboardInterrupt("Menu cancelled by user") from None
        if not raw:
            return default_index
        if raw.isdigit() and 1 <= int(raw) <= len(options):
            return int(raw) - 1
        print_warning(f"Please enter a number between 1 and {len(options)}.")


def _decode_key_bytes(fd: int, first: bytes) -> str:
    """Decode one keypress, including multi-byte UTF-8 characters.

    Bytes are consumed one at a time so a byte belonging to the next
    keypress (e.g. Enter right after an accented character) is never
    swallowed.

    Args:
        fd: File descriptor to read continuation bytes from.
        first: Already-read first byte of the keypress.
    """
    import select

    buf = bytearray(first)
    while len(buf) < 4:  # UTF-8 sequences are at most 4 bytes.
        try:
            return bytes(buf).decode("utf-8")
        except UnicodeDecodeError as exc:
            if exc.reason != "unexpected end of data":
                break  # Invalid bytes: do not eat the next keypress.
        if not select.select([fd], [], [], 0.05)[0]:
            break
        chunk = os.read(fd, 1)
        if not chunk:
            break
        buf += chunk
    return bytes(buf).decode("utf-8", errors="replace")


def _read_key_posix() -> str:
    """Read a single keypress on POSIX with working lone-Esc support.

    ``readchar.readkey()`` blocks waiting for a second byte after ESC,
    so pressing Esc alone never returns (it hangs until the next key).
    This reader switches stdin to cbreak mode, reads one byte, and when
    it is ESC waits briefly for sequence bytes: if none arrive, the user
    pressed Esc alone and ``"\\x1b"`` is returned.
    """
    import select
    import termios

    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    new = termios.tcgetattr(fd)
    new[3] &= ~(termios.ICANON | termios.ECHO | termios.IGNBRK | termios.BRKINT)
    try:
        # TCSANOW (not TCSAFLUSH): never discard queued input, otherwise
        # pasted text or fast typing would lose everything but one byte.
        termios.tcsetattr(fd, termios.TCSANOW, new)
        first = os.read(fd, 1)
        if not first or first == b"\x03":
            # EOF or Ctrl-C (in case ISIG is disabled).
            raise KeyboardInterrupt("Menu cancelled by user")
        if first != b"\x1b":
            return _decode_key_bytes(fd, first)
        # ESC: distinguish a lone Esc press from an escape sequence
        # such as arrows (``\\x1b[A`` ...) which arrive all at once.
        # Bytes are consumed one at a time and the drain stops at the
        # end of a complete CSI/SS3 sequence, so a key typed right
        # after an arrow key is never swallowed.
        if not select.select([fd], [], [], 0.08)[0]:
            return "\x1b"
        seq = bytearray(b"\x1b")
        while len(seq) < 8:
            if not select.select([fd], [], [], 0.02)[0]:
                break
            chunk = os.read(fd, 1)
            if not chunk:
                break
            seq += chunk
            if re.fullmatch(rb"\x1b(?:\[[0-9;]*[@-~]|O[@-~])", bytes(seq)):
                break
        return bytes(seq).decode("utf-8", errors="replace")
    finally:
        try:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)
        except termios.error:
            pass


def _read_key() -> str:
    """Read a single keypress.

    On POSIX a small custom reader is used so a lone Esc press works
    (``readchar.readkey()`` blocks forever waiting for sequence bytes
    after ESC). On Windows ``readchar`` already handles Esc correctly.
    """
    if os.name == "nt":
        return readchar.readkey()
    return _read_key_posix()


def _discard_typeahead() -> None:
    """Drop already-queued input so stale keys do not leak into the menu."""
    if os.name == "nt" or not sys.stdin.isatty():
        return
    try:
        import select

        fd = sys.stdin.fileno()
        while select.select([fd], [], [], 0)[0]:
            if not os.read(fd, 1024):
                break
    except (OSError, ValueError):
        pass


def select_from_list(
    options: list[str] | Sequence[str],
    prompt: str,
    default_index: int = 0,
    *,
    allow_filter: bool = True,
    is_disabled: Callable[[str], bool] | None = None,
) -> int:
    """Let the user pick one option with arrow keys (stable, lightweight).

    Features:
    - Up/Down (or j/k), Home/End, PageUp/PageDown navigation.
    - Type-to-filter on long lists, Backspace to erase, Ctrl-U or Esc to
      clear the filter.
    - Esc with no active filter acts as "back": it returns the last
      selectable entry (codebase convention: last option is always the
      safe Back / Cancel / No choice). It never raises and never crashes.
      Only Ctrl-C / Ctrl-D interrupt (``KeyboardInterrupt``).
    - Windowed view that adapts to the terminal height on every keypress.
    - Separator rows (empty or ``── ...``) are shown dimmed and skipped.
    - Numbered ``input()`` fallback when stdin/stdout is not a TTY.

    Args:
        options: Choices to display (must contain at least one item).
        prompt: Header text shown above the list.
        default_index: Initially highlighted index.
        allow_filter: Enable type-to-filter for lists with more than 4 items.
        is_disabled: Optional predicate marking non-selectable rows.
            Defaults to detecting empty / ``──`` separator rows.

    Returns:
        Index of the selected option in the original ``options`` list.
    """
    items = list(options)
    if not items:
        raise ValueError("select_from_list() requires at least one option.")

    disabled = is_disabled or _is_disabled
    is_off = [disabled(o) for o in items]

    # Clamp the default to a selectable row when possible.
    default_index = max(0, min(default_index, len(items) - 1))
    if is_off[default_index]:
        for i, off in enumerate(is_off):
            if not off:
                default_index = i
                break

    # Non-interactive environments (pipes, dumb terminals, CI): fallback.
    if not _is_interactive():
        return _fallback_select(items, prompt, default_index)

    filter_enabled = allow_filter and len(items) > 4
    query = ""
    # Position inside the *filtered* list.
    cursor = 0
    # First visible row inside the filtered list.
    scroll = 0

    def visible_indices() -> list[int]:
        if not filter_enabled or not query:
            return list(range(len(items)))
        lowered = query.lower()
        return [i for i, o in enumerate(items) if lowered in o.lower()]

    def move_cursor(filtered: list[int], delta: int) -> int:
        """Move to the next selectable row, wrapping around."""
        if not filtered:
            return 0
        pos = cursor % max(1, len(filtered))
        for _ in range(len(filtered)):
            pos = (pos + delta) % len(filtered)
            if not is_off[filtered[pos]]:
                return pos
        return cursor  # all rows disabled: stay put

    def jump_to_edge(filtered: list[int], to_start: bool) -> int:
        if not filtered:
            return 0
        rng = range(len(filtered)) if to_start else range(len(filtered) - 1, -1, -1)
        for pos in rng:
            if not is_off[filtered[pos]]:
                return pos
        return cursor

    def render_menu(filtered: list[int]) -> Group:
        """Build the renderable for the current frame.

        Everything is Rich ``Text`` objects, so Rich owns width
        measurement, cropping and cursor repositioning. Hand-written
        ANSI line-shuffling can no longer desync on soft-wrapped lines.
        """
        nonlocal scroll
        width = console.width
        height = console.size.height
        reserved = 7 if filter_enabled else 6
        page = max(_MIN_VISIBLE_ROWS, min(_MAX_VISIBLE_ROWS, height - reserved))
        page = min(page, max(1, len(filtered)))

        if filtered:
            cursor_clamped = max(0, min(cursor, len(filtered) - 1))
        else:
            cursor_clamped = 0

        if cursor_clamped < scroll:
            scroll = cursor_clamped
        elif cursor_clamped >= scroll + page:
            scroll = cursor_clamped - page + 1
        scroll = max(0, min(scroll, max(0, len(filtered) - page)))

        inner_width = max(10, width - 6)
        lines: list[Text] = []

        # Title line with position counter.
        title = Text()
        title.append("❯ ", style="bold cyan")
        title.append(prompt, style="bold cyan")
        if filtered:
            title.append(f" [{cursor_clamped + 1}/{len(filtered)}]", style="dim")
        title.truncate(max_width=width, overflow="ellipsis", pad=False)
        lines.append(title)

        # Active filter line.
        if filter_enabled and query:
            lines.append(Text(f"/{_truncate(query, inner_width)}▌", style="dim"))

        window = filtered[scroll: scroll + page]

        # Top overflow hint.
        if scroll > 0:
            lines.append(Text(f"  ▲ {scroll} more", style="dim"))

        for pos_in_window, original_idx in enumerate(window):
            pos = scroll + pos_in_window
            label = _truncate(items[original_idx], inner_width)
            if is_off[original_idx]:
                lines.append(Text(f"    {label}", style="dim"))
            elif pos == cursor_clamped:
                lines.append(Text(f"❯ {label}", style="bold bright_cyan"))
            else:
                lines.append(Text(f"  {label}"))

        # Bottom overflow hint.
        remaining = len(filtered) - (scroll + page)
        if remaining > 0:
            lines.append(Text(f"  ▼ {remaining} more", style="dim"))

        if not filtered:
            lines.append(Text(f'  No match for "/{query}".', style="dim"))

        # Footer hints (contextual: show filter actions while filtering).
        if filter_enabled and query:
            lines.append(
                Text(
                    "↑↓ move · ⌫ erase char · Ctrl-U / Esc clear filter · Enter select",
                    style="dim",
                )
            )
        elif filter_enabled:
            lines.append(
                Text(
                    "↑↓/j/k move · PgUp/PgDn page · type to filter · "
                    "Enter select · Esc back",
                    style="dim",
                )
            )
        else:
            lines.append(Text("↑↓ move · Enter select · Esc back", style="dim"))
        return Group(*lines)

    # Initial cursor on the default entry (mapped into filtered space).
    initial_filtered = visible_indices()
    if initial_filtered and default_index in initial_filtered:
        pos = initial_filtered.index(default_index)
        if not is_off[default_index]:
            cursor = pos
        else:
            cursor = jump_to_edge(initial_filtered, True)
    else:
        cursor = jump_to_edge(initial_filtered, True)

    out = sys.stdout
    out.write(_HIDE_CURSOR)
    out.flush()
    _discard_typeahead()
    console.print()  # breathing room between previous output and this menu.
    live = Live(
        render_menu(visible_indices()),
        console=console,
        auto_refresh=False,
        vertical_overflow="visible",
    )
    try:
        live.start()
        live.refresh()  # emit the initial frame immediately
        filtered = visible_indices()

        while True:
            try:
                key = _read_key()
            except KeyboardInterrupt:
                raise KeyboardInterrupt("Menu cancelled by user") from None

            enter_key = getattr(readchar.key, "ENTER", "\r")
            if key in ("\r", "\n", enter_key):
                if filtered and not is_off[filtered[cursor % len(filtered)]]:
                    chosen = filtered[cursor % len(filtered)]
                    break
                continue
            if key in (getattr(readchar.key, "CTRL_C", "\x03"), "\x03"):
                raise KeyboardInterrupt("Menu cancelled by user")
            if key in (getattr(readchar.key, "CTRL_D", "\x04"), "\x04"):
                raise KeyboardInterrupt("Menu cancelled by user")

            up_key = getattr(readchar.key, "UP", "\x1b[A")
            down_key = getattr(readchar.key, "DOWN", "\x1b[B")
            home_key = getattr(readchar.key, "HOME", "\x1b[H")
            end_key = getattr(readchar.key, "END", "\x1b[F")
            page_up = getattr(readchar.key, "PAGE_UP", "\x1b[5~")
            page_down = getattr(readchar.key, "PAGE_DOWN", "\x1b[6~")
            backspace = getattr(readchar.key, "BACKSPACE", "\x7f")
            esc_keys = tuple(
                k for k in (getattr(readchar.key, "ESC", "\x1b"), "\x1b") if k
            )

            # Vim-style keys (j/k/g/G) navigate only when no filter is
            # active; once the user starts typing they become filter text.
            vim_nav = not query

            if key == up_key or (vim_nav and key == "k"):
                cursor = move_cursor(filtered, -1)
            elif key == down_key or (vim_nav and key == "j"):
                cursor = move_cursor(filtered, +1)
            elif key == home_key or (vim_nav and key == "g"):
                cursor = jump_to_edge(filtered, True)
            elif key == end_key or (vim_nav and key == "G"):
                cursor = jump_to_edge(filtered, False)
            elif key == page_up:
                height = shutil.get_terminal_size(fallback=(80, 24)).lines
                step = max(1, min(_MAX_VISIBLE_ROWS, height - 8))
                for _ in range(step):
                    cursor = move_cursor(filtered, -1)
            elif key == page_down:
                height = shutil.get_terminal_size(fallback=(80, 24)).lines
                step = max(1, min(_MAX_VISIBLE_ROWS, height - 8))
                for _ in range(step):
                    cursor = move_cursor(filtered, +1)
            elif key in (backspace, "\x7f", "\x08"):
                if filter_enabled and query:
                    query = query[:-1]
                    filtered = visible_indices()
                    cursor = jump_to_edge(filtered, True)
                else:
                    continue
            elif key == "\x15":  # Ctrl-U: clear the whole filter.
                if filter_enabled and query:
                    query = ""
                    filtered = visible_indices()
                    cursor = jump_to_edge(filtered, True)
                else:
                    continue
            elif key in esc_keys:
                if filter_enabled and query:
                    query = ""
                    filtered = visible_indices()
                    cursor = jump_to_edge(filtered, True)
                elif filtered:
                    # Esc means "back": return the last selectable entry.
                    # Codebase convention: the last option is always the
                    # safe choice (Back / Cancel / No), so this never
                    # triggers an action by mistake and never crashes.
                    # Only Ctrl-C / Ctrl-D raise (real interruption).
                    back_pos = jump_to_edge(filtered, False)
                    if is_off[filtered[back_pos]]:
                        continue  # degenerate: no selectable entry.
                    chosen = filtered[back_pos]
                    break
                else:
                    continue
            elif filter_enabled and len(key) == 1 and key.isprintable() and key != "\t":
                # Type-to-filter: any printable char narrows long lists.
                query += key
                filtered = visible_indices()
                cursor = jump_to_edge(filtered, True)
            else:
                continue

            # Recompute the filtered view if navigation keys were remapped.
            filtered = visible_indices()
            if filtered:
                cursor = max(0, min(cursor, len(filtered) - 1))
            live.update(render_menu(filtered), refresh=True)
    finally:
        live.stop()
        out.write(_SHOW_CURSOR)
        out.flush()

    console.print(f"\n[bold cyan]❯ {prompt}[/bold cyan] [green]{items[chosen]}[/green]")
    return chosen


def clean_title(title: str) -> str:
    """Remove season/part markers to improve search queries.

    Example:
        "One Piece Season 4" -> "One Piece"
        "From Old Country Bumpkin to Master Swordsman II" -> "From Old Country Bumpkin to Master Swordsman"
    """
    patterns = [
        r"\s+Season\s+\d+",
        r"\s+S\d+",
        r"\s+Part\s+\d+",
        r"\s+Cour\s+\d+",
        r"\s+\d+(st|nd|rd|th)\s+Season",
        r"\s+-\s+\d+",
        # Trailing Roman numerals I–IV (season suffixes like "Title II")
        r"\s+(?:IV|III|II|I)$",
    ]

    cleaned = title
    for pattern in patterns:
        cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE)

    return cleaned.strip()
