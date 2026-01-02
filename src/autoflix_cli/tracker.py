import json
import os
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any
from platformdirs import user_data_dir
from urllib.parse import urlparse


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

    def _to_relative(self, url: str) -> str:
        """Convert an absolute URL to a relative path."""
        if not url:
            return ""
        try:
            parsed = urlparse(url)
            # If it has a scheme (http/https), return path + query
            if parsed.scheme:
                path = parsed.path
                if parsed.query:
                    path += "?" + parsed.query
                return path
            return url  # Already relative or invalid
        except Exception:
            return url

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

        # Convert URLs to relative paths (except logo which is external)
        series_rel = self._to_relative(series_url)
        season_rel = self._to_relative(season_url)
        episode_rel = self._to_relative(episode_url)

        # Update specific series progress
        key = f"{provider}|{series_title}"
        entry = {
            "provider": provider,
            "series_title": series_title,
            "season_title": season_title,
            "episode_title": episode_title,
            "series_url": series_rel,
            "season_url": season_rel,
            "episode_url": episode_rel,
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

    def get_history(self) -> list[Dict[str, Any]]:
        """Get all history entries sorted by last_watched (descending)."""
        if "history" not in self.data:
            return []

        entries = list(self.data["history"].values())
        # Parse date and sort
        entries.sort(
            key=lambda x: datetime.fromisoformat(x["last_watched"]), reverse=True
        )
        return entries

    def delete_history_item(self, provider: str, series_title: str):
        """Delete a specific history entry."""
        if "history" not in self.data:
            return

        key = f"{provider}|{series_title}"
        if key in self.data["history"]:
            del self.data["history"][key]

            # If this was the last global watched, we might want to clear it or find the next one
            # For simplicity, we just check if it matches and clear it
            last_global = self.data.get("last_watched_global")
            if (
                last_global
                and last_global.get("provider") == provider
                and last_global.get("series_title") == series_title
            ):
                self.data["last_watched_global"] = None

            self._save_data()

    # --- AniList Integration ---

    def get_anilist_token(self) -> Optional[str]:
        """Get the stored AniList token."""
        return self.data.get("anilist_token")

    def set_anilist_token(self, token: str):
        """Save the AniList token."""
        self.data["anilist_token"] = token
        self._save_data()

    def get_anilist_mapping(
        self, provider: str, series_title: str, season_title: Optional[str] = None
    ) -> Optional[int]:
        """Get the AniList media ID for a given series and season."""
        if "anilist_mappings" not in self.data:
            return None

        # Try specific season mapping first if provided
        if season_title:
            key = f"{provider}|{series_title}|{season_title}"
            if key in self.data["anilist_mappings"]:
                return self.data["anilist_mappings"][key]

        # Fallback to series-only mapping (legacy support or if no season provided)
        # However, for fixing the bug, we might want to be stricter?
        # Let's keep fallback only if season_title is NOT provided.
        if not season_title:
            key = f"{provider}|{series_title}"
            return self.data["anilist_mappings"].get(key)

        return None

    def set_anilist_mapping(
        self,
        provider: str,
        series_title: str,
        media_id: int,
        season_title: Optional[str] = None,
    ):
        """Save the mapping between a series and an AniList media ID."""
        if "anilist_mappings" not in self.data:
            self.data["anilist_mappings"] = {}

        if season_title:
            key = f"{provider}|{series_title}|{season_title}"
        else:
            key = f"{provider}|{series_title}"

        self.data["anilist_mappings"][key] = media_id
        self._save_data()


# Global instance
tracker = ProgressTracker()
