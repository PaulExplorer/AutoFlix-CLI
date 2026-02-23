from .tracker import tracker
from .cli_utils import (
    clear_screen,
    print_header,
    print_warning,
    select_from_list,
    print_success,
)
from .handlers import anime_sama, coflix, french_stream, wiflix, goldenanime, goldenms


def handle_resume(data):
    """Dispatch resume to provider."""
    provider = data["provider"]
    if provider == "Anime-Sama":
        anime_sama.resume_anime_sama(data)
    elif provider == "Coflix":
        coflix.resume_coflix(data)
    elif provider == "French-Stream":
        french_stream.resume_french_stream(data)
    elif provider == "Wiflix":
        print_warning(
            "Resume for Wiflix not manually implemented here (usually direct)."
        )
    elif provider == "GoldenAnime":
        goldenanime.resume_goldenanime(data)
    elif provider == "GoldenMS":
        goldenms.resume_goldenms(data)


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
            series = entry["series_title"]
            season = entry["season_title"]
            episode = entry["episode_title"]

            if provider == "Coflix":
                if season == "Movie" or episode == "Movie":
                    text = f"[{provider}] {series} (Movie)"
                else:
                    clean_season = season.replace(series, "").strip(" -")
                    if not clean_season:
                        clean_season = season
                    text = f"[{provider}] {series} - {clean_season} - {episode}"
            elif provider == "French-Stream":
                if season == "Movie" or episode == "Movie":
                    text = f"[{provider}] {series} (Movie)"
                else:
                    text = f"[{provider}] {series} - {episode}"
            elif provider == "GoldenAnime":
                text = f"[{provider}] {series} - {episode}"
            elif provider == "GoldenMS":
                if season == "Movie" or episode == "Movie":
                    text = f"[{provider}] {series} (Movie)"
                else:
                    text = f"[{provider}] {series} - {season} - {episode}"
            else:
                text = f"[{provider}] {series} - {season} - {episode}"

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
