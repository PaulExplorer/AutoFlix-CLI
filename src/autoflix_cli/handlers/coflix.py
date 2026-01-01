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

        # Loop to allow retrying with another player
        while True:
            player_idx = select_from_list(
                [f"Player : {p.name}" for p in supported_players] + ["← Back"],
                "🎮 Select Player:",
            )

            if player_idx == len(supported_players):  # Back
                return

            success = play_video(
                supported_players[player_idx].url,
                headers={
                    "Referer": "https://lecteurvideo.com/",
                },
                title=content.title,
            )

            if success:
                tracker.save_progress(
                    provider="Coflix",
                    series_title=content.title,
                    season_title="Movie",
                    episode_title="Movie",
                    series_url=content.url,
                    season_url=content.url,
                    episode_url=content.url,
                    logo_url=content.img,
                )

                return  # Playback succeeded, exit
            else:
                # Playback failed, ask if they want to retry
                retry = select_from_list(
                    ["Try another server/player", "← Back to main menu"],
                    "What would you like to do?",
                )
                if retry == 1:  # Back
                    return
                # Otherwise continue the loop to choose another player

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

            # Get episode links and filter for supported players
            links = coflix.get_episode(selected_episode.url).players
            supported_links = [link for link in links if player.is_supported(link.url)]

            if not supported_links:
                print_warning("No supported players found.")
                return

            # Loop to allow retrying with another player
            playback_success = False
            while True:
                player_idx = select_from_list(
                    [f"Player : {link.name}" for link in supported_links] + ["← Back"],
                    "🎮 Select Player:",
                )

                if player_idx == len(supported_links):  # Back
                    return

                success = play_video(
                    supported_links[player_idx].url,
                    headers={
                        "Referer": "https://lecteurvideo.com/",
                    },
                    title=f"{selected_season_access.title} - {selected_episode.title}",
                )

                if success:
                    tracker.save_progress(
                        provider="Coflix",
                        series_title=content.title,
                        season_title=selected_season_access.title,
                        episode_title=selected_episode.title,
                        series_url=content.url,
                        season_url=selected_season_access.url,
                        episode_url=selected_episode.url,
                        logo_url=content.img,
                    )

                    playback_success = True
                    break  # Playback succeeded, exit player loop
                else:
                    # Playback failed, ask if they want to retry
                    retry = select_from_list(
                        ["Try another server/player", "← Back to main menu"],
                        "What would you like to do?",
                    )
                    if retry == 1:  # Back
                        return
                    # Otherwise continue the loop to choose another player

            if playback_success:
                if ep_idx + 1 < len(season.episodes):
                    next_ep = season.episodes[ep_idx + 1]
                    choice = select_from_list(
                        ["Yes", "No"], f"Play next episode: {next_ep.title}?"
                    )
                    if choice == 0:
                        ep_idx += 1
                        continue
                break


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
        links = coflix.get_episode(selected_episode.url).players
        supported = [link for link in links if player.is_supported(link.url)]

        if not supported:
            return

        playback_success = False
        for idx in range(len(supported)):
            # Auto try logic or list? Let's use list for consistency if previous failed
            # But here we might want to just pick first valid?
            # Let's show list to be safe or just try first.
            # Showing list is safer.
            player_idx = select_from_list(
                [f"Player : {link.name}" for link in supported] + ["← Back"],
                "🎮 Select Player:",
            )

            if player_idx == len(supported):
                return

            success = play_video(
                supported[player_idx].url,
                headers={"Referer": "https://lecteurvideo.com/"},
                title=f"{data['season_title']} - {selected_episode.title}",
            )
            if success:
                tracker.save_progress(
                    provider="Coflix",
                    series_title=data["series_title"],
                    season_title=data["season_title"],
                    episode_title=selected_episode.title,
                    series_url=data["series_url"],
                    season_url=data["season_url"],
                    episode_url=selected_episode.url,
                    logo_url=data.get("logo_url"),
                )
                playback_success = True
                break

            if select_from_list(["Retry", "Back"], "Action?") == 1:
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
