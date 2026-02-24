from .cli_utils import (
    clear_screen,
    select_from_list,
    print_header,
    print_success,
    print_error,
    print_info,
    print_warning,
    get_user_input,
    pause,
    console,
)
from .update_checker import check_update
from .tracker import tracker
from .providers_registry import registry
from .languages import LANGUAGES, get_language_display, get_all_languages
from .handlers import (
    anime_sama,
    coflix,
    french_stream,
    wiflix,
    anilist,
    goldenanime,
    goldenms,
)
from . import history_ui
from . import proxy
import sys
import os
import signal


def check_language_setup():
    """Verify if a language is set, if not, prompt for first setup."""
    if not tracker.get_language():
        clear_screen()
        print_header("AutoFlix - First Launch Setup")
        print_info("Please select your preferred language.")
        print_info(
            "This will filter available providers and set default subtitle languages."
        )

        langs = get_all_languages()

        choice = select_from_list([l[1] for l in langs], "Choice:")
        selected_lang = langs[choice][0]
        tracker.set_language(selected_lang)
        print_success(f"Language set to: {langs[choice][1]}")
        pause()


def main():
    # Register Providers
    registry.register(
        "🎌 Anime-Sama (Anime and animated movies)",
        anime_sama.handle_anime_sama,
        supported_languages=["fr"],
    )
    registry.register(
        "✨ GoldenAnime (VO and Subtitles)",
        goldenanime.handle_goldenanime,
        supported_languages=None,
    )
    registry.register(
        "🌟 GoldenMS (Movies & Series)",
        goldenms.handle_goldenms,
        supported_languages=None,
    )
    registry.register(
        "🎬 Coflix (Series and movies)",
        coflix.handle_coflix,
        supported_languages=["fr"],
    )
    registry.register(
        "🇫🇷 French-Stream (Series and movies)",
        french_stream.handle_french_stream,
        supported_languages=["fr"],
    )

    # Check for updates
    if check_update():
        pause()

    # Check for language setup
    check_language_setup()

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
            elif last_watch["provider"] == "GoldenAnime":
                resume_text = f"▶ Resume: {series_name} - {ep_name}"
            elif last_watch["provider"] == "GoldenMS":
                if season_name == "Movie" or ep_name == "Movie":
                    resume_text = f"▶ Resume: {series_name} (Movie)"
                else:
                    resume_text = f"▶ Resume: {series_name} - {season_name} - {ep_name}"
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
            user_lang = tracker.get_language()
            available_providers = registry.get_providers(user_lang)

            p_items = [p["name"] for p in available_providers] + ["← Back"]
            p_idx = select_from_list(p_items, "Select a Provider:")

            if p_idx < len(available_providers):
                available_providers[p_idx]["handler"]()
            continue

        if choice_idx == settings_idx:
            # Settings menu
            while True:
                clear_screen()
                print_header("⚙ Settings")
                token = tracker.get_anilist_token()
                lang = tracker.get_language()

                lang_display = get_language_display(lang)

                opts = [
                    f"Update AniList Token ({'Set' if token else 'Not Set'})",
                    f"Update Language ({lang_display})",
                    "Back",
                ]

                s_choice = select_from_list(opts, "Select Setting:")

                if s_choice == 0:
                    new_token = get_user_input("Enter new AniList Token")
                    if new_token:
                        tracker.set_anilist_token(new_token)
                        print_success("Token saved.")
                        pause()
                elif s_choice == 1:
                    langs = get_all_languages()
                    l_choice = select_from_list(
                        [l[1] for l in langs], "Select Language:"
                    )
                    tracker.set_language(langs[l_choice][0])
                    print_success(f"Language updated to: {langs[l_choice][1]}")
                    pause()
                else:
                    break
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
