from ..scraping import wiflix, player
from ..scraping.objects import WiflixMovie, WiflixSeriesSeason
from ..cli_utils import (
    select_from_list,
    print_header,
    print_info,
    print_warning,
    get_user_input,
    console,
)
from ..player_manager import play_video, select_and_play_player
from ..tracker import tracker


def handle_wiflix():
    """Handle Wiflix provider flow."""
    print_header("🎬 Wiflix")

    query = get_user_input("Search query")

    print_info(f"Searching for: [cyan]{query}[/cyan]")
    results = wiflix.search(query)

    if not results:
        print_warning("No results found.")
        return

    choice_idx = select_from_list(
        [f"{r.title} ({', '.join(r.genres)})" for r in results], "📺 Search Results:"
    )
    selection = results[choice_idx]

    print_info(f"Loading [cyan]{selection.title}[/cyan]...")
    content = wiflix.get_content(selection.url)

    if isinstance(content, WiflixMovie):
        console.print(f"\n[bold]🎬 Movie:[/bold] [cyan]{content.title}[/cyan]")
        if not content.players:
            print_warning("No players found.")
            return
        supported_players = [p for p in content.players if player.is_supported(p.url)]
        if not supported_players:
            print_warning("No supported players found.")
            return

        select_and_play_player(supported_players, wiflix.website_origin, content.title)

    elif isinstance(content, WiflixSeriesSeason):
        console.print(
            f"\n[bold]📺 Series:[/bold] [cyan]{content.title} - {content.season}[/cyan]"
        )

        # episodes is a dict {lang: [Episode]}
        langs = list(content.episodes.keys())
        if not langs:
            print_warning("No episodes found.")
            return

        lang_idx = select_from_list(langs, "🌍 Select Language:")
        selected_lang = langs[lang_idx]
        episodes = content.episodes[selected_lang]

        ep_idx = select_from_list([e.title for e in episodes], "📺 Select Episode:")

        while True:
            selected_episode = episodes[ep_idx]

            if not selected_episode.players:
                print_warning("No players found for this episode.")
                return

            supported_players = [
                p for p in selected_episode.players if player.is_supported(p.url)
            ]
            if not supported_players:
                print_warning("No supported players found.")
                return

            success = select_and_play_player(
                supported_players,
                wiflix.website_origin,
                f"{content.title} - {selected_episode.title}",
            )

            if success:
                tracker.save_progress(
                    provider="Wiflix",
                    series_title=content.title,
                    season_title=content.season,
                    episode_title=selected_episode.title,
                    series_url=content.url,
                    season_url=content.url,
                    episode_url="",
                    logo_url=content.img,
                )

                if ep_idx + 1 < len(episodes):
                    next_ep = episodes[ep_idx + 1]
                    choice = select_from_list(
                        ["Yes", "No"], f"Play next episode: {next_ep.title}?"
                    )
                    if choice == 0:
                        ep_idx += 1
                        continue
            break
