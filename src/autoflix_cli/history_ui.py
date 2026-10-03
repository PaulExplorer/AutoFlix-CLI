from .tracker import tracker
from .cli_utils import (
    clear_screen,
    print_header,
    print_warning,
    select_from_list,
    print_success,
)
from .handlers import anime_sama, coflix, french_stream, goldenanime, goldenms, arkanime


def handle_resume(data):
    """Dispatch resume to provider."""
    provider = data["provider"]
    if provider == "Anime-Sama":
        anime_sama.resume_anime_sama(data)
    elif provider == "Coflix":
        coflix.resume_coflix(data)
    elif provider == "French-Stream":
        french_stream.resume_french_stream(data)
    elif provider == "GoldenAnime":
        goldenanime.resume_goldenanime(data)
    elif provider == "GoldenMS":
        goldenms.resume_goldenms(data)
    elif provider == "ArkAnime":
        arkanime.resume_arkanime(data)


def format_history_entry(entry: dict) -> str:
    """Format the 'Series - Season - Episode' part of a history entry.

    Shared by the history view and the home "Resume" shortcut so the
    two can never diverge.
    """
    provider = entry.get("provider", "")
    series = entry.get("series_title", "")
    season = entry.get("season_title", "")
    episode = entry.get("episode_title", "")
    is_movie = season == "Movie" or episode == "Movie"

    if provider == "Coflix":
        if is_movie:
            return f"{series} (Movie)"
        clean_season = season.replace(series, "").strip(" -")
        if not clean_season:
            clean_season = season
        return f"{series} - {clean_season} - {episode}"
    if provider == "French-Stream":
        if is_movie:
            return f"{series} (Movie)"
        return f"{series} - {episode}"
    if provider == "GoldenAnime":
        return f"{series} - {episode}"
    if provider == "GoldenMS":
        if is_movie:
            return f"{series} (Movie)"
        return f"{series} - {season} - {episode}"
    return f"{series} - {season} - {episode}"


def handle_history():
    """Display history list and allow resume/delete."""
    while True:
        clear_screen()
        print_header("📜 My History")

        history = tracker.get_history()
        if not history:
            print_warning("No history found.")
            input("\nPress Enter to go back...")
            return

        options = []
        for entry in history:
            provider = entry["provider"]
            text = f"[{provider}] {format_history_entry(entry)}"
            options.append(text)

        options.append("← Back")

        choice_idx = select_from_list(options, "Select an entry to resume or delete:")

        if choice_idx == len(history):  # Back
            return

        selected_entry = history[choice_idx]

        action = select_from_list(["▶ Resume", "❌ Delete", "← Cancel"], "Action:")

        if action == 0:  # Resume
            handle_resume(selected_entry)
        elif action == 1:  # Delete
            tracker.delete_history_item(
                selected_entry["provider"], selected_entry["series_title"]
            )
            print_success("Entry deleted.")
