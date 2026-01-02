from ..scraping import coflix, player
from ..scraping.objects import CoflixMovie, CoflixSeries
from ..cli_utils import (
    select_from_list,
    print_header,
    print_info,
    print_warning,
    get_user_input,
    console,
)
from ..player_manager import play_video
from ..tracker import tracker
from .playback import play_episode_flow


def handle_coflix():
    """Handle Coflix provider flow."""
    coflix.get_website_url()

    print_header("🎬 Coflix")
    query = get_user_input("Search query")

    print_info(f"Searching for: [cyan]{query}[/cyan]")
    results = coflix.search(query)

    if not results:
        print_warning("No results found.")
        return

    choice_idx = select_from_list([f"{r.title}" for r in results], "📺 Search Results:")
    selection = results[choice_idx]

    print_info(f"Loading [cyan]{selection.title}[/cyan]...")
    content = coflix.get_content(selection.url)

    if isinstance(content, CoflixMovie):
        console.print(f"\n[bold]🎬 Movie:[/bold] [cyan]{content.title}[/cyan]\n")
        if not content.players:
            print_warning("No players found.")
            return
        supported_players = [p for p in content.players if player.is_supported(p.url)]
        if not supported_players:
            print_warning("No supported players found.")
            return

        headers = {"Referer": "https://lecteurvideo.com/"}
        play_episode_flow(
            provider_name="Coflix",
            series_title=content.title,
            season_title="Movie",
            series_url=content.url,
            season_url=content.url,
            logo_url=content.img,
            headers=headers,
            episode=content,  # Movie object should behave like Episode if it has players
        )

    elif isinstance(content, CoflixSeries):
        console.print(f"\n[bold]📺 Series:[/bold] [cyan]{content.title}[/cyan]\n")

        if not content.seasons:
            print_warning("No seasons found.")
            return

        # Check for saved progress for this specific series
        saved_progress = tracker.get_series_progress("Coflix", content.title)
        if saved_progress:
            choice = select_from_list(
                [
                    f"Resume {saved_progress['season_title']} - {saved_progress['episode_title']}",
                    "Browse Seasons",
                ],
                f"Found saved progress for {content.title}:",
            )
            if choice == 0:
                resume_coflix(saved_progress)
                return

        season_idx = select_from_list(
            [s.title for s in content.seasons], "📺 Select Season:"
        )
        selected_season_access = content.seasons[season_idx]

        print_info(f"Loading [cyan]{selected_season_access.title}[/cyan]...")
        season = coflix.get_season(selected_season_access.url)

        if not season.episodes:
            print_warning("No episodes found.")
            return

        ep_idx = select_from_list(
            [e.title for e in season.episodes], "📺 Select Episode:"
        )

        while True:
            selected_episode = season.episodes[ep_idx]
            headers = {"Referer": "https://lecteurvideo.com/"}

            # Fetch players for the episode
            ep_details = coflix.get_episode(selected_episode.url)

            success = play_episode_flow(
                provider_name="Coflix",
                series_title=content.title,
                season_title=selected_season_access.title,
                episode=ep_details,
                series_url=content.url,
                season_url=selected_season_access.url,
                logo_url=content.img,
                headers=headers,
            )

            if success:
                if ep_idx + 1 < len(season.episodes):
                    next_ep = season.episodes[ep_idx + 1]
                    choice = select_from_list(
                        ["Yes", "No"], f"Play next episode: {next_ep.title}?"
                    )
                    if choice == 0:
                        ep_idx += 1
                        continue
                break
            else:
                return


def resume_coflix(data):
    """Resume Coflix playback."""
    print_info(f"Resuming [cyan]{data['series_title']}[/cyan]...")

    # For Coflix, we need to re-fetch the SEASON page to get episode list,
    # OR re-fetch the EPISODE page directly if we have the URL?
    # Coflix episodes have dedicated URLs.
    # But to play "Next", we need the season list.
    # data['season_url'] should be the season page.

    print_info(f"Loading Season: {data['season_url']}")
    try:
        season = coflix.get_season(data["season_url"])
    except Exception as e:
        print_error(f"Could not load season: {e}")
        return

    if not season.episodes:
        return

    # Find episode index
    start_ep_idx = 0
    saved_ep_title = data["episode_title"]

    for i, ep in enumerate(season.episodes):
        if ep.title == saved_ep_title:
            start_ep_idx = i
            break

    options = [
        (
            f"Continue (Next: {season.episodes[start_ep_idx+1].title})"
            if start_ep_idx + 1 < len(season.episodes)
            else "No next episode"
        ),
        f"Watch again ({saved_ep_title})",
        "Cancel",
    ]
    choice = select_from_list(options, "What would you like to do?")

    if choice == 2:
        return
    elif choice == 0:
        if start_ep_idx + 1 < len(season.episodes):
            start_ep_idx += 1
        else:
            return

    ep_idx = start_ep_idx

    while True:
        selected_episode = season.episodes[ep_idx]
        headers = {"Referer": "https://lecteurvideo.com/"}
        ep_details = coflix.get_episode(selected_episode.url)

        success = play_episode_flow(
            provider_name="Coflix",
            series_title=data["series_title"],
            season_title=data["season_title"],
            episode=ep_details,
            series_url=data["series_url"],
            season_url=data["season_url"],
            logo_url=data.get("logo_url"),
            headers=headers,
        )

        if success:
            playback_success = True
        else:
            return

        if playback_success:
            if ep_idx + 1 < len(season.episodes):
                if (
                    select_from_list(
                        ["Yes", "No"],
                        f"Play next: {season.episodes[ep_idx+1].title}?",
                    )
                    == 0
                ):
                    ep_idx += 1
                    continue
            break
