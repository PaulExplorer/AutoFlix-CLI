import json
import os
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any
from platformdirs import user_data_dir


class ProgressTracker:
    def __init__(self):
        self.app_name = "AutoFlixCLI"
        self.app_author = "PaulExplorer"
        self.data_dir = Path(user_data_dir(self.app_name, self.app_author))
        self.data_file = self.data_dir / "progress.json"

        self.data = self._load_data()

    def _load_data(self) -> Dict[str, Any]:
        """Load progress data from JSON file."""
        if not self.data_file.exists():
            return {}

        try:
            with open(self.data_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return {}

    def _save_data(self):
        """Save progress data to JSON file."""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        try:
            with open(self.data_file, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=4, ensure_ascii=False)
        except OSError as e:
            print(f"Warning: Could not save progress: {e}")

    def save_progress(
        self,
        provider: str,
        series_title: str,
        season_title: str,
        episode_title: str,
        series_url: str,
        season_url: str,
        episode_url: str,
        logo_url: Optional[str] = None,
    ):
        """
        Save the progress for a specific episode.

        Args:
            provider: The name of the provider (e.g., 'Anime-Sama').
            series_title: Title of the series.
            season_title: Title of the season.
            episode_title: Title of the episode (e.g., 'Episode 1').
            series_url: URL of the series page.
            season_url: URL of the season page.
            episode_url: URL of the episode page or player.
            logo_url: Optional URL for the series cover image.
        """
        if "history" not in self.data:
            self.data["history"] = {}

        # Update specific series progress
        key = f"{provider}|{series_title}"
        entry = {
            "provider": provider,
            "series_title": series_title,
            "season_title": season_title,
            "episode_title": episode_title,
            "series_url": series_url,
            "season_url": season_url,
            "episode_url": episode_url,
            "last_watched": datetime.now().isoformat(),
            "logo_url": logo_url,
        }
        self.data["history"][key] = entry

        # Update last global watched for "Quick Resume"
        self.data["last_watched_global"] = entry

        self._save_data()

    def get_last_global(self) -> Optional[Dict[str, Any]]:
        """Get the absolute last thing watched."""
        return self.data.get("last_watched_global")

    def get_series_progress(
        self, provider: str, series_title: str
    ) -> Optional[Dict[str, Any]]:
        """Get the last progress for a specific series."""
        if "history" not in self.data:
            return None
        return self.data["history"].get(f"{provider}|{series_title}")


# Global instance
tracker = ProgressTracker()
