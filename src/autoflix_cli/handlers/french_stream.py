from ..scraping import french_stream, player
from ..scraping.objects import FrenchStreamMovie, FrenchStreamSeason
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


def resolve_url(url, base):
    """Helper to resolve partial URLs."""
    if not url:
        return ""
    if url.startswith("http"):
        return url
    return base.rstrip("/") + "/" + url.lstrip("/")


def handle_french_stream():
    """Handle French-Stream provider flow."""
    french_stream.get_website_url()

    print_header("🇫🇷 French-Stream")
    query = get_user_input("Search query")

    print_info(f"Searching for: [cyan]{query}[/cyan]")
    results = french_stream.search(query)

    if not results:
        print_warning("No results found.")
        return

    choice_idx = select_from_list([f"{r.title}" for r in results], "📺 Search Results:")
    selection = results[choice_idx]

    print_info(f"Loading [cyan]{selection.title}[/cyan]...")
    content = french_stream.get_content(selection.url)

    if isinstance(content, FrenchStreamMovie):
        console.print(f"\n[bold]🎬 Movie:[/bold] [cyan]{content.title}[/cyan]")
        if not content.players:
            print_warning("No players found.")
            return
        supported_players = [p for p in content.players if player.is_supported(p.url)]
        if not supported_players:
            print_warning("No supported players found.")
            return

        success = select_and_play_player(
            supported_players, french_stream.website_origin, content.title
        )
        if success:
            tracker.save_progress(
                provider="French-Stream",
                series_title=content.title,
                season_title="Movie",
                episode_title="Movie",
                series_url=content.url,
                season_url=content.url,
                episode_url=content.url,
                logo_url=content.img,
            )

    elif isinstance(content, FrenchStreamSeason):
        # ... logic for series similar to main.py ...
        console.print(f"\n[bold]📺 Series:[/bold] [cyan]{content.title}[/cyan]")

        # Check for saved progress
        saved_progress = tracker.get_series_progress("French-Stream", content.title)
        if saved_progress:
            choice = select_from_list(
                [
                    f"Resume {saved_progress['season_title']} - {saved_progress['episode_title']}",
                    "Browse Episodes",
                ],
                f"Found saved progress for {content.title}:",
            )
            if choice == 0:
                resume_french_stream(saved_progress)
                return

        # episodes is dict {lang: [Episode]}
        langs = list(content.episodes.keys())
        if not langs:
            print_warning("No episodes found.")
            return

        if len(langs) == 1:
            lang = langs[0]
        else:
            lang = langs[select_from_list(langs, "🌍 Select Language:")]

        episodes = content.episodes[lang]

        ep_idx = select_from_list([e.title for e in episodes], "📺 Select Episode:")

        while True:
            selected_episode = episodes[ep_idx]
            if not selected_episode.players:
                print_warning("No players found for this episode.")
                return
            supported = [
                p for p in selected_episode.players if player.is_supported(p.url)
            ]
            if not supported:
                print_warning("No supported players found.")
                return

            success = select_and_play_player(
                supported,
                french_stream.website_origin,
                f"{content.title} - {selected_episode.title}",
            )

            if success:
                tracker.save_progress(
                    provider="French-Stream",
                    series_title=content.title,
                    season_title=content.title,
                    episode_title=selected_episode.title,
                    series_url=content.url,
                    season_url=content.url,
                    episode_url="",
                    logo_url=content.img,
                )
                if ep_idx + 1 < len(episodes):
                    if (
                        select_from_list(
                            ["Yes", "No"], f"Play next: {episodes[ep_idx+1].title}?"
                        )
                        == 0
                    ):
                        ep_idx += 1
                        continue
            break


def resume_french_stream(data):
    """Resume French-Stream playback."""
    print_info(f"Resuming [cyan]{data['series_title']}[/cyan]...")

    data["series_url"] = resolve_url(data["series_url"], french_stream.website_origin)
    data["season_url"] = resolve_url(data["season_url"], french_stream.website_origin)
    if "episode_url" in data:
        data["episode_url"] = resolve_url(
            data["episode_url"], french_stream.website_origin
        )

    # We load content from SERIES URL (or movie url)
    content = french_stream.get_content(data["series_url"])

    if isinstance(content, FrenchStreamMovie):
        if not content.players:
            return
        supported = [p for p in content.players if player.is_supported(p.url)]
        select_and_play_player(supported, french_stream.website_origin, content.title)
        return

    elif isinstance(content, FrenchStreamSeason):
        langs = list(content.episodes.keys())
        if not langs:
            return

        # Ask language (simple assumption: user knows which lang they watched, or we could save it)
        if len(langs) == 1:
            lang = langs[0]
        else:
            lang = langs[select_from_list(langs, "🌍 Select Language:")]

        episodes = content.episodes[lang]

        start_ep_idx = 0
        for i, ep in enumerate(episodes):
            if ep.title == data["episode_title"]:
                start_ep_idx = i
                break

        options = [
            (
                f"Continue (Next: {episodes[start_ep_idx+1].title})"
                if start_ep_idx + 1 < len(episodes)
                else "No next episode"
            ),
            f"Watch again ({data['episode_title']})",
            "Cancel",
        ]
        choice = select_from_list(options, "What would you like to do?")
        if choice == 2:
            return
        elif choice == 0:
            if start_ep_idx + 1 < len(episodes):
                start_ep_idx += 1
            else:
                return

        ep_idx = start_ep_idx
        while True:
            selected_episode = episodes[ep_idx]
            if not selected_episode.players:
                return
            supported = [
                p for p in selected_episode.players if player.is_supported(p.url)
            ]

            success = select_and_play_player(
                supported,
                french_stream.website_origin,
                f"{content.title} - {selected_episode.title}",
            )

            if success:
                tracker.save_progress(
                    provider="French-Stream",
                    series_title=content.title,
                    season_title=content.title,
                    episode_title=selected_episode.title,
                    series_url=content.url,
                    season_url=content.url,
                    episode_url="",
                    logo_url=None,
                )
                if ep_idx + 1 < len(episodes):
                    if (
                        select_from_list(
                            ["Yes", "No"], f"Play next: {episodes[ep_idx+1].title}?"
                        )
                        == 0
                    ):
                        ep_idx += 1
                        continue
            break
