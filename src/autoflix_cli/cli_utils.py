import os
import readchar
from rich.console import Console, Group
from rich.panel import Panel
from rich.text import Text
from rich.live import Live
from rich import print as rprint

console = Console()


def clear_screen():
    """Clear the terminal screen."""
    os.system("cls" if os.name == "nt" else "clear")


def get_user_input(prompt: str) -> str:
    """
    Get user input with a styled prompt.

    Args:
        prompt: The prompt text to display

    Returns:
        The user's input as a string
    """
    styled_prompt = Text(f"\n❯ {prompt}: ", style="bold cyan")
    console.print(styled_prompt, end="")
    return input().strip()


def select_from_list(options: list[str], prompt: str) -> int:
    """
    Display an interactive menu where users can navigate with arrow keys.

    Args:
        options: List of options to display
        prompt: Header text for the menu

    Returns:
        Index of the selected option (0-based)
    """
    selected_index = 0
    window_size = 10  # Number of items to show at once
    start_index = 0

    def generate_renderable():
        nonlocal start_index

        # Adjust start_index to keep selected_index in view
        if selected_index < start_index:
            start_index = selected_index
        elif selected_index >= start_index + window_size:
            start_index = selected_index - window_size + 1

        # Ensure start_index is valid
        start_index = max(0, min(start_index, len(options) - window_size))
        end_index = min(len(options), start_index + window_size)

        lines = [Text(f"\n❯ {prompt}", style="bold cyan")]

        # Up arrow indicator
        if start_index > 0:
            lines.append(Text("  ↑ ...", style="dim"))

        for idx in range(start_index, end_index):
            option = options[idx]
            if idx == selected_index:
                lines.append(Text(f"  ● {option}", style="green bold"))
            else:
                lines.append(Text(f"    {option}", style="white"))

        # Down arrow indicator
        if end_index < len(options):
            lines.append(Text("  ↓ ...", style="dim"))

        return Group(*lines)

    with Live(generate_renderable(), refresh_per_second=10, transient=True) as live:
        while True:
            key = readchar.readkey()

            if key == readchar.key.UP:
                selected_index = (selected_index - 1) % len(options)
                live.update(generate_renderable())
            elif key == readchar.key.DOWN:
                selected_index = (selected_index + 1) % len(options)
                live.update(generate_renderable())
            elif key == readchar.key.ENTER:
                break
            elif key == readchar.key.CTRL_C:
                raise KeyboardInterrupt("Menu cancelled by user")

    console.print(
        f"\n[bold cyan]❯ {prompt}[/bold cyan] [green]{options[selected_index]}[/green]"
    )
    return selected_index


def print_header(text: str):
    """
    Print a styled header with a decorative panel.

    Args:
        text: Header text to display
    """
    console.print()
    panel = Panel(
        Text(text, style="bold white", justify="center"),
        style="cyan",
        border_style="bright_cyan",
        padding=(0, 2),
    )
    console.print(panel)


def print_success(message: str):
    """
    Print a success message with a green checkmark.

    Args:
        message: Success message to display
    """
    console.print(f"[green]✓[/green] {message}")


def print_error(message: str):
    """
    Print an error message with a red X.

    Args:
        message: Error message to display
    """
    console.print(f"[red]✗[/red] {message}")


def print_info(message: str):
    """
    Print an info message with a blue icon.

    Args:
        message: Info message to display
    """
    console.print(f"[blue]ℹ[/blue] {message}")


def print_warning(message: str):
    """
    Print a warning message with a yellow icon.

    Args:
        message: Warning message to display
    """
    console.print(f"[yellow]⚠[/yellow] {message}")
