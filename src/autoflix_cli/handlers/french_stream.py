from ..cli_utils import (
    console,
    get_user_input,
    pause,
    print_header,
    print_info,
    print_warning,
    select_from_list,
)
from ..scraping import french_stream, player
from ..scraping.objects import FrenchStreamMovie, FrenchStreamSeason
from ..tracker import tracker
from .playback import play_episode_flow


def resolve_url(url, base):
    """Helper to resolve partial URLs."""
    if not url:
        return ""
    if url.startswith("http"):
        return url
    return base.rstrip("/") + "/" + url.lstrip("/")


def open_result(selection):
    """Open a search result: load the content, browse and play.

    Returns once playback ends or the user backs out (back to the
    search-results list in the handler flow).
    """
    print_info(f"Loading [cyan]{selection.title}[/cyan]...")
    content = french_stream.get_content(selection.url)

    if isinstance(content, FrenchStreamMovie):
        console.print(f"\n[bold]🎬 Movie:[/bold] [cyan]{content.title}[/cyan]")
        if not content.players:
            print_warning("No players found.")
            pause()
            return
        supported_players = [p for p in content.players if player.is_supported(p.url)]
        if not supported_players:
            print_warning("No supported players found.")
            pause()
            return

        play_episode_flow(
            provider_name="French-Stream",
            series_title=content.title,
            season_title="Movie",
            is_movie=True,
            series_url=content.url,
            season_url=content.url,
            logo_url=content.img,
            headers={"Referer": french_stream.website_origin},
            episode=content,
        )
        return

    if not isinstance(content, FrenchStreamSeason):
        return

    console.print(f"\n[bold]📺 Series:[/bold] [cyan]{content.title}[/cyan]")

    saved_progress = tracker.get_series_progress("French-Stream", content.title)
    if saved_progress:
        choice = select_from_list(
            [
                f"Resume {saved_progress['season_title']} - {saved_progress['episode_title']}",
                "Browse Episodes",
                "← Cancel",
            ],
            f"Found saved progress for {content.title}:",
        )
        if choice == 0:
            resume_french_stream(saved_progress)
            return
        if choice == 2:
            return

    langs = list(content.episodes.keys())
    if not langs:
        print_warning("No episodes found.")
        pause()
        return

    if len(langs) == 1:
        lang = langs[0]
    else:
        lang_options = langs + ["← Back"]
        lang_idx = select_from_list(lang_options, "🌍 Select Language:")
        if lang_idx == len(langs):
            return
        lang = langs[lang_idx]

    episodes = content.episodes[lang]

    ep_options = [e.title for e in episodes] + ["← Back"]
    ep_idx = select_from_list(ep_options, "📺 Select Episode:")
    if ep_idx == len(episodes):
        return

    while True:
        selected_episode = episodes[ep_idx]
        if not selected_episode.players:
            print_warning(f"No players found for [cyan]{selected_episode.title}[/cyan].")
            pause()
            ep_idx += 1
            if ep_idx >= len(episodes):
                break
            continue
        supported = [
            p for p in selected_episode.players if player.is_supported(p.url)
        ]
        if not supported:
            print_warning(f"No supported players for [cyan]{selected_episode.title}[/cyan].")
            pause()
            ep_idx += 1
            if ep_idx >= len(episodes):
                break
            continue

        success = play_episode_flow(
            provider_name="French-Stream",
            series_title=content.title,
            season_title=content.title,
            series_url=content.url,
            season_url=content.url,
            headers={"Referer": french_stream.website_origin},
            episode=selected_episode,
        )

        if success:
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


def handle_french_stream():
    """Handle French-Stream provider flow."""
    print_header("🇫🇷 French-Stream")

    while True:
        query = get_user_input("Search query (or 'exit' to back)")
        if not query or query.lower() == "exit":
            return

        print_info(f"Searching for: [cyan]{query}[/cyan]")
        results = french_stream.search(query)

        if not results:
            print_warning("No results found.")
            pause()
            continue

        while True:
            options = [f"{r.title}" for r in results] + ["← Back"]
            choice_idx = select_from_list(options, "📺 Search Results:")

            if choice_idx == len(results):
                break

            open_result(results[choice_idx])


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
        # Movie Resume
        if not content.players:
            return

        play_episode_flow(
            provider_name="French-Stream",
            series_title=content.title,
            season_title="Movie",
            is_movie=True,
            series_url=content.url,
            season_url=content.url,
            logo_url=content.img,
            headers={"Referer": french_stream.website_origin},
            episode=content,
        )
        return

    elif isinstance(content, FrenchStreamSeason):
        langs = list(content.episodes.keys())
        if not langs:
            return

        # Ask language (simple assumption: user knows which lang they watched, or we could save it)
        if len(langs) == 1:
            lang = langs[0]
        else:
            lang_options = langs + ["← Back"]
            lang_idx = select_from_list(lang_options, "🌍 Select Language:")
            if lang_idx == len(langs):
                return
            lang = langs[lang_idx]

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

            success = play_episode_flow(
                provider_name="French-Stream",
                series_title=content.title,
                season_title=content.title,
                series_url=content.url,
                season_url=content.url,
                headers={"Referer": french_stream.website_origin},
                episode=selected_episode,
            )

            if success:
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
