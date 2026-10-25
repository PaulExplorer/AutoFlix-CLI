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
from .player_manager import (
    PLAYERS,
    get_player_display,
    get_all_players,
    is_custom_player,
    slugify_custom_name,
)
from .handlers import (
    anime_sama,
    coflix,
    french_stream,
    anilist,
    goldenanime,
    goldenms,
    arkanime,
)
from . import history_ui
from . import proxy
from .handlers.devtest import (
    handle_dev_playback_mode_test,
    handle_dev_scraper_test,
)
from .log import apply_developer_logging, setup_logging
import sys
import importlib.metadata


_GITHUB_URL = "https://github.com/PaulExplorer/AutoFlix-CLI"
_ISSUES_URL = "https://github.com/PaulExplorer/AutoFlix-CLI/issues"


def _get_version() -> str:
    try:
        return importlib.metadata.version("autoflix-cli")
    except importlib.metadata.PackageNotFoundError:
        return "dev"


def _handle_about() -> None:
    """Display the About page."""
    clear_screen()
    version = _get_version()
    print_header("ℹ About AutoFlix CLI")
    console.print(f"\n  [bold cyan]AutoFlix CLI[/bold cyan]  [dim]v{version}[/dim]")
    console.print(
        f"\n  [dim]GitHub:[/dim]  [cyan underline]{_GITHUB_URL}[/cyan underline]"
    )
    console.print()
    console.print(
        "  [yellow]⚠[/yellow]  [bold]I don't catch every bug![/bold]\n"
        "  If something breaks, don't hesitate to open an issue — reports are very welcome.\n"
        f"  [dim]→[/dim] [cyan underline]{_ISSUES_URL}[/cyan underline]"
    )
    console.print(
        "\n  [dim](You can also open it in French if you prefer / "
        "Vous pouvez aussi l'ouvrir en français si vous préférez.)[/dim]"
    )
    console.print()
    pause()


def _handle_add_custom_player():
    name = get_user_input("Custom player name (e.g. Celluloid)")
    if not name:
        return
    command = get_user_input(
        "Command (use {url} for stream URL, e.g. celluloid {url})",
        default=name,
    )
    if not command:
        return
    code = slugify_custom_name(name)
    existing = tracker.get_custom_players()
    if code in existing:
        print_warning(f"A custom player '{name}' already exists.")
        pause()
        return
    tracker.add_custom_player(code, name.strip(), command.strip())
    print_success(f"Custom player '{name}' added (always via proxy).")
    pause()


def _handle_custom_players_menu():
    while True:
        clear_screen()
        print_header("Custom players", "Always played via proxy")
        customs = tracker.get_custom_players()
        opts = [f"{cfg.get('display', code)} ({cfg.get('command', '')})" for code, cfg in customs.items()]
        opts += ["+ Add a custom player"]
        if customs:
            opts += ["- Remove a custom player"]
        opts += ["← Back"]
        choice = select_from_list(opts, "Custom players:")
        if choice == len(opts) - 1:
            return
        if opts[choice] == "+ Add a custom player":
            _handle_add_custom_player()
        elif opts[choice] == "- Remove a custom player":
            codes = list(customs.keys())
            labels = [customs[c].get("display", c) for c in codes] + ["← Back"]
            idx = select_from_list(labels, "Remove which player?")
            if idx < len(codes):
                tracker.remove_custom_player(codes[idx])
                print_success("Custom player removed.")
                pause()
        else:
            pause()


def _first_launch_setup():
    """Guided first-launch setup shown only once (when no language is saved).

    Steps:
      1. Language
      2. Default player
      3. Auto-pick best source
      4. Ask for subtitles before playback
      5. Closing tip about AniList and other settings
    """
    clear_screen()
    print_header("🚀 AutoFlix CLI — First Launch Setup",
                 "You can change all of these later in ⚙ Settings")

    # ── Step 1: Language ──────────────────────────────────────────────────
    console.print("\n[bold cyan]Step 1 / 4[/bold cyan] — [bold]Preferred language[/bold]")
    console.print(
        "[dim]Filters available providers and sets the default subtitle language.[/dim]"
    )
    langs = get_all_languages()
    lang_choice = select_from_list([l[1] for l in langs], "Choose your language:")
    selected_lang = langs[lang_choice][0]
    tracker.set_language(selected_lang)
    print_success(f"Language set to: {langs[lang_choice][1]}")

    # ── Step 2: Default player ────────────────────────────────────────────
    console.print("\n[bold cyan]Step 2 / 4[/bold cyan] — [bold]Default video player[/bold]")
    console.print(
        "[dim]The player launched automatically for each stream. "
        "You can also add custom players in Settings.[/dim]"
    )
    players = get_all_players()
    player_choice = select_from_list(
        [p[1] for p in players], "Choose your default player:"
    )
    tracker.set_player(players[player_choice][0])
    print_success(f"Default player set to: {players[player_choice][1]}")

    # ── Step 3: Auto-pick best source ─────────────────────────────────────
    console.print("\n[bold cyan]Step 3 / 4[/bold cyan] — [bold]Auto-pick best source[/bold]")
    console.print(
        "[dim]When ON, AutoFlix probes all available sources and plays the best "
        "one automatically without asking. When OFF, you choose the source each time.[/dim]"
    )
    auto_choice = select_from_list(
        ["ON  — Pick best source automatically",
         "OFF — Let me choose the source each time"],
        "Auto-pick best source:",
    )
    tracker.set_auto_source(auto_choice == 0)
    print_success("Auto-pick: " + ("enabled." if auto_choice == 0 else "disabled."))

    # ── Step 4: Ask for subtitles ─────────────────────────────────────────
    console.print("\n[bold cyan]Step 4 / 4[/bold cyan] — [bold]Subtitle prompt[/bold]")
    console.print(
        "[dim]When ON, AutoFlix asks before each episode whether to search for "
        "external subtitles. GoldenMS and GoldenAnime always ask regardless of this setting.[/dim]"
    )
    sub_choice = select_from_list(
        ["ON  — Ask for subtitles before each playback",
         "OFF — Start playback without asking"],
        "Subtitle prompt:",
    )
    tracker.set_ask_subtitles(sub_choice == 0)
    print_success("Subtitle prompt: " + ("enabled." if sub_choice == 0 else "disabled."))

    # ── Closing tip ───────────────────────────────────────────────────────
    console.print()
    console.print(
        "[bold green]✓ Setup complete![/bold green] "
        "More options are available in [bold]⚙ Settings[/bold], including:\n"
        "  [cyan]•[/cyan] AniList sync (track your watch progress automatically)\n"
        "  [cyan]•[/cyan] Custom video players\n"
        "  [cyan]•[/cyan] Developer / debug mode"
    )
    pause()


def check_language_setup():
    """Run first-launch setup when no language has been configured yet."""
    if not tracker.get_language():
        _first_launch_setup()


def _run():
    setup_logging()
    apply_developer_logging(tracker.get_developer_mode())

    # Register Providers
    registry.register(
        "🎌 Anime-Sama (Anime and animated movies)",
        anime_sama.handle_anime_sama,
        supported_languages=["fr"],
    )
    registry.register(
        "⛩️ ArkAnime (Anime & Animations)",
        arkanime.handle_arkanime,
        supported_languages=["fr", "en"], # Assuming multi or depending on ArkAnime source
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
            resume_text = history_ui.format_history_entry(last_watch)

            menu_items.append(f"▶ Resume: {resume_text}")
            resume_idx = 0

        # 2. AniList
        if tracker.get_anilist_token():
            menu_items.append("📋 AniList Lists (Continue, Planning, Completed...)")
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
                player = tracker.get_player()
                dev_mode = tracker.get_developer_mode()
                auto_source = tracker.get_auto_source()
                ask_subs = tracker.get_ask_subtitles()

                lang_display = get_language_display(lang)
                player_display = get_player_display(player)
                dev_display = "ON" if dev_mode else "OFF"
                auto_display = "ON" if auto_source else "OFF"
                ask_subs_display = "ON" if ask_subs else "OFF"

                opts = [
                    f"Update AniList Token ({'Set' if token else 'Not Set'})",
                    f"Update Language ({lang_display})",
                    f"Choose default Player ({player_display})",
                    "Manage custom players",
                    f"Auto-pick the best source ({auto_display})",
                    f"Ask for subtitles on playback ({ask_subs_display})",
                    f"Developer Mode ({dev_display})",
                ]
                if dev_mode:
                    opts.append("Test embed URL (dev)")
                    opts.append("Test playback modes (dev)")
                opts.append("ℹ About")
                opts.append("Back")

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

                elif s_choice == 2:

                    players = get_all_players()
                    p_choice = select_from_list(
                        [p[1] for p in players], "Select default player:"
                    )
                    tracker.set_player(players[p_choice][0])
                    print_success(f"Player updated to: {players[p_choice][1]}")
                    pause()

                elif s_choice == 3:
                    _handle_custom_players_menu()

                elif s_choice == 4:
                    tracker.set_auto_source(not auto_source)
                    print_success(
                        "Auto-pick enabled, the best working source will be "
                        "played without asking."
                        if not auto_source
                        else "Auto-pick disabled."
                    )
                    pause()

                elif s_choice == 5:
                    tracker.set_ask_subtitles(not ask_subs)
                    print_success(
                        "Subtitles prompt enabled, you will be asked before "
                        "each playback (Golden sources always ask)."
                        if not ask_subs
                        else "Subtitles prompt disabled, playback starts "
                        "without asking (Golden sources still ask)."
                    )
                    pause()

                elif s_choice == 6:
                    tracker.set_developer_mode(not dev_mode)
                    apply_developer_logging(not dev_mode)
                    state = "enabled" if not dev_mode else "disabled"
                    print_success(f"Developer mode {state}.")
                    pause()

                elif dev_mode and s_choice == 7:
                    handle_dev_scraper_test()
                elif dev_mode and s_choice == 8:
                    handle_dev_playback_mode_test()

                elif s_choice == opts.index("ℹ About"):
                    _handle_about()

                else:
                    break
            continue

        # Exit
        print_success("Goodbye!")
        proxy.stop_proxy_server()
        return


def main():
    """Application entry point with a clean exit on Ctrl-C.

    The installed ``autoflix`` script calls this directly, bypassing the
    ``__main__`` guard below, so interruption must be handled here to
    avoid a traceback and to always stop the proxy server.
    """
    try:
        _run()
    except KeyboardInterrupt:
        print("\nGoodbye!")
        try:
            proxy.stop_proxy_server()
        except Exception:
            pass
        sys.exit(0)
    except Exception as e:
        if tracker.get_developer_mode():
            console.print_exception()
        print_error(f"An unexpected error occurred: {e}")
        try:
            proxy.stop_proxy_server()
        except Exception:
            pass
        sys.exit(1)


if __name__ == "__main__":
    main()
