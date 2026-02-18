import urllib.request
import json
import importlib.metadata
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

console = Console()


def get_latest_version(package_name: str) -> str:
    """
    Get the latest version of a package from PyPI.
    """
    try:
        url = f"https://pypi.org/pypi/{package_name}/json"
        with urllib.request.urlopen(url, timeout=2) as response:
            data = json.loads(response.read().decode())
            return data["info"]["version"]
    except Exception:
        return None


def check_update(package_name: str = "autoflix-cli"):
    """
    Check if a new version of the package is available and notify the user.
    """
    try:
        current_version = importlib.metadata.version(package_name)
    except importlib.metadata.PackageNotFoundError:
        # Package not installed (e.g., dev mode), skip check
        return

    if not current_version:
        return

    latest_version = get_latest_version(package_name)

    if latest_version and latest_version > current_version:
        panel_content = Text()
        panel_content.append(
            f"\nExample: A new version of {package_name} is available!\n",
            style="bold yellow",
        )
        panel_content.append(f"Installed: {current_version}\n", style="red")
        panel_content.append(f"Latest:    {latest_version}\n\n", style="green")
        panel_content.append(
            f"Run 'pip install --upgrade {package_name}' to update.\n",
            style="bold white",
        )
        panel_content.append(
            f"Or run 'uv tool update {package_name}' to update with uv.\n",
            style="bold white",
        )

        console.print(
            Panel(
                panel_content,
                title="[bold yellow]Update Available[/bold yellow]",
                border_style="yellow",
                expand=False,
            )
        )
        return True

    return False
