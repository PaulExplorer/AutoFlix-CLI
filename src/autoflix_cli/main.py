from .cli_utils import (
    clear_screen,
    select_from_list,
    print_header,
    print_success,
    print_error,
    print_info,
    print_warning,
    get_user_input,
    console,
)
from .tracker import tracker
from .handlers import anime_sama, coflix, french_stream, wiflix, anilist
from . import history_ui
from . import proxy
import sys
import os
import signal


def main():
    # Start Proxy Server
    proxy.start_proxy_server()

    while True:
        clear_screen()
        print_header("AutoFlix CLI - Home")

        # 1. Continue Watching (History)
        last_watch = tracker.get_last_global()
        menu_items = []
        resume_idx = -1
        anilist_resume_idx = -1

        if last_watch:
            series_name = last_watch["series_title"]
            season_name = last_watch["season_title"]
            ep_name = last_watch["episode_title"]

            # Formatting logic similar to history_ui
            if last_watch["provider"] == "Coflix":
                if season_name == "Movie" or ep_name == "Movie":
                    resume_text = f"▶ Resume: {series_name} (Movie)"
                else:
                    clean_season = season_name.replace(series_name, "").strip(" -")
                    if not clean_season:
                        clean_season = season_name
                    resume_text = (
                        f"▶ Resume: {series_name} - {clean_season} - {ep_name}"
                    )
            elif last_watch["provider"] == "French-Stream":
                if season_name == "Movie" or ep_name == "Movie":
                    resume_text = f"▶ Resume: {series_name} (Movie)"
                else:
                    resume_text = f"▶ Resume: {series_name} - {ep_name}"
            else:
                resume_text = f"▶ Resume: {series_name} - {season_name} - {ep_name}"

            menu_items.append(resume_text)
            resume_idx = 0

        # 2. Continue from AniList
        if tracker.get_anilist_token():
            menu_items.append("▶ Continue from AniList")
            anilist_resume_idx = len(menu_items) - 1

        # 3. My History
        menu_items.append("📜 My History")
        history_idx = len(menu_items) - 1

        # 4. Providers
        menu_items.append("🌍 Browse Providers")
        providers_idx = len(menu_items) - 1

        # 5. Settings / Exit
        menu_items.append("⚙ Settings (AniList)")
        settings_idx = len(menu_items) - 1

        menu_items.append("❌ Exit")

        choice_idx = select_from_list(menu_items, "What would you like to do?")

        if last_watch and choice_idx == resume_idx:
            history_ui.handle_resume(last_watch)
            continue

        if choice_idx == anilist_resume_idx:
            anilist.handle_anilist_continue()
            continue

        if choice_idx == history_idx:
            history_ui.handle_history()
            continue

        if choice_idx == providers_idx:
            providers = [
                (
                    "🎌 Anime-Sama (Anime and animated movies)",
                    anime_sama.handle_anime_sama,
                ),
                ("🎬 Coflix (Series and movies)", coflix.handle_coflix),
                (
                    "🇫🇷 French-Stream (Series and movies - Often lower quality)",
                    french_stream.handle_french_stream,
                ),
                # ("🎬 Wiflix", wiflix.handle_wiflix), don't work anymore
                ("← Back", None),
            ]
            p_idx = select_from_list([p[0] for p in providers], "Select a Provider:")
            if p_idx < len(providers) - 1:  # Not Back
                providers[p_idx][1]()
            continue

        if choice_idx == settings_idx:
            # Simple settings menu for token
            token = tracker.get_anilist_token()
            print_info(
                f"Current Token: {token[:10]}..." if token else "Current Token: Not Set"
            )
            if select_from_list(["Update Token", "Back"], "Settings") == 0:
                new_token = get_user_input("Enter new AniList Token")
                if new_token:
                    tracker.set_anilist_token(new_token)
                    print_success("Token saved.")
            continue

        # Exit
        print_success("Goodbye!")
        proxy.stop_proxy_server()
        os._exit(0)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nGoodbye!")
        proxy.stop_proxy_server()
        os._exit(0)
