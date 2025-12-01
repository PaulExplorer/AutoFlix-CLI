import os
import inquirer
from rich.console import Console
from rich.panel import Panel
from rich.text import Text
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
    styled_prompt = Text(f"❯ {prompt}: ", style="bold cyan")
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
    questions = [
        inquirer.List(
            "choice",
            message=prompt,
            choices=options,
            carousel=True,  # Circular navigation
        ),
    ]

    answers = inquirer.prompt(questions)

    # If user presses Ctrl+C, answers will be None
    if answers is None:
        raise KeyboardInterrupt("Menu cancelled by user")

    # Find the index of the selected option
    selected = answers["choice"]
    return options.index(selected)


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
    console.print()


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
