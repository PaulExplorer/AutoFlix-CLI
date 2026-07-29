from ..scraping import coflix, player
from ..scraping.objects import CoflixMovie, CoflixSeries
from ..cli_utils import (
    select_from_list,
    print_header,
    print_info,
    print_error,
    print_warning,
    get_user_input,
    console,
    pause,
)
from ..player_manager import play_video
from ..tracker import tracker
from .playback import play_episode_flow


def handle_coflix():
    """Handle Coflix provider flow."""
    coflix.get_website_url()

    print_header("🎬 Coflix")

    while True:
        query = get_user_input("Search query (or 'exit' to back)")
        if not query or query.lower() == "exit":
            break

        print_info(f"Searching for: [cyan]{query}[/cyan]")
        results = coflix.search(query)

        if not results:
            print_warning("No results found.")
            pause()
            continue

        options = [f"{r.title}" for r in results] + ["← Back"]
        choice_idx = select_from_list(options, "📺 Search Results:")

        if choice_idx == len(results):
            continue

        selection = results[choice_idx]

        print_info(f"Loading [cyan]{selection.title}[/cyan]...")
        try:
            content = coflix.get_content(selection.url)
        except Exception as e:
            print_error(f"Error loading content: {e}")
            pause()
            continue

        if isinstance(content, CoflixMovie):
            console.print(f"\n[bold]🎬 Movie:[/bold] [cyan]{content.title}[/cyan]\n")

            # Check for saved progress (Movie Resume Fix)
            saved_progress = tracker.get_series_progress("Coflix", content.title)
            if saved_progress:
                choice = select_from_list(
                    ["Watch again/Resume", "Cancel"],
                    f"Found saved progress for {content.title}:",
                )
                if choice == 0:
                    resume_coflix(saved_progress)
                    continue

            if not content.players:
                print_warning("No players found.")
                pause()
                continue
            supported_players = [
                p for p in content.players if player.is_supported(p.url)
            ]
            if not supported_players:
                print_warning("No supported players found.")
                pause()
                continue

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
                pause()
                continue

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
                    continue

            season_idx = select_from_list(
                [s.title for s in content.seasons], "📺 Select Season:"
            )
            selected_season = content.seasons[season_idx]

            if not selected_season.episodes:
                print_warning("No episodes found.")
                pause()
                continue

            ep_idx = select_from_list(
                [e.title for e in selected_season.episodes], "📺 Select Episode:"
            )

            while True:
                selected_episode = selected_season.episodes[ep_idx]
                headers = {"Referer": "https://lecteurvideo.com/"}

                try:
                    ep_details = coflix.get_episode(selected_episode.url)
                except Exception as e:
                    print_error(f"Error loading episode: {e}")
                    pause()
                    break

                success = play_episode_flow(
                    provider_name="Coflix",
                    series_title=content.title,
                    season_title=selected_season.title,
                    episode=ep_details,
                    series_url=content.url,
                    season_url=content.url,
                    logo_url=content.img,
                    headers=headers,
                )

                if success:
                    if ep_idx + 1 < len(selected_season.episodes):
                        next_ep = selected_season.episodes[ep_idx + 1]
                        choice = select_from_list(
                            ["Yes", "No"], f"Play next episode: {next_ep.title}?"
                        )
                        if choice == 0:
                            ep_idx += 1
                            continue
                    break
                else:
                    break


def resume_coflix(data):
    """Resume Coflix playback."""
    # Ensure origin is set so we can resolve relative URLs
    coflix.get_website_url()

    def resolve_url(u):
        if not u:
            return ""
        if u.startswith("http"):
            return u
        return coflix.website_origin.rstrip("/") + "/" + u.lstrip("/")

    # Resolve URLs in data
    data["series_url"] = resolve_url(data["series_url"])
    data["season_url"] = resolve_url(data["season_url"])

    print_info(f"Resuming [cyan]{data['series_title']}[/cyan]...")

    # Handle Movie
    if data["season_title"] == "Movie":
        print_info(f"Loading Movie: {data['series_url']}")
        try:
            content = coflix.get_content(data["series_url"])
        except Exception as e:
            print_error(f"Could not load movie: {e}")
            pause()
            return

        if not isinstance(content, CoflixMovie):
            print_error("Expected a Movie but got something else.")
            pause()
            return

        options = ["Watch again", "Cancel"]
        choice = select_from_list(options, "What would you like to do?")

        if choice == 1:
            return

        # Watch again
        headers = {"Referer": "https://lecteurvideo.com/"}
        play_episode_flow(
            provider_name="Coflix",
            series_title=content.title,
            season_title="Movie",
            series_url=content.url,
            season_url=content.url,
            logo_url=content.img,
            headers=headers,
            episode=content,
        )
        return

    # Handle Series
    print_info(f"Loading Series: {data['series_url']}")
    try:
        content = coflix.get_content(data["series_url"])
    except Exception as e:
        print_error(f"Could not load series: {e}")
        pause()
        return

    if not isinstance(content, CoflixSeries):
        print_error("Expected a Series but got something else.")
        pause()
        return

    # Find matching season
    saved_season_title = data.get("season_title", "")
    selected_season = None
    for s in content.seasons:
        if s.title == saved_season_title:
            selected_season = s
            break
    if not selected_season or not selected_season.episodes:
        print_warning("No episodes found in season.")
        pause()
        return

    # Find episode index
    start_ep_idx = 0
    saved_ep_title = data["episode_title"]

    for i, ep in enumerate(selected_season.episodes):
        if ep.title.split(" ")[-1] == saved_ep_title.split(" ")[-1]:
            start_ep_idx = i
            break

    options = [
        (
            f"Continue (Next: {selected_season.episodes[start_ep_idx+1].title})"
            if start_ep_idx + 1 < len(selected_season.episodes)
            else "No next episode"
        ),
        f"Watch again ({saved_ep_title})",
        "Cancel",
    ]
    choice = select_from_list(options, "What would you like to do?")

    if choice == 2:
        return
    elif choice == 0:
        if start_ep_idx + 1 < len(selected_season.episodes):
            start_ep_idx += 1
        else:
            return

    ep_idx = start_ep_idx

    while True:
        selected_episode = selected_season.episodes[ep_idx]
        headers = {"Referer": "https://lecteurvideo.com/"}

        try:
            ep_details = coflix.get_episode(selected_episode.url)
        except Exception as e:
            print_error(f"Error loading episode: {e}")
            pause()
            break

        success = play_episode_flow(
            provider_name="Coflix",
            series_title=data["series_title"],
            season_title=selected_season.title,
            episode=ep_details,
            series_url=data["series_url"],
            season_url=data["series_url"],
            logo_url=data.get("logo_url"),
            headers=headers,
        )

        if success:
            playback_success = True
        else:
            return

        if playback_success:
            if ep_idx + 1 < len(selected_season.episodes):
                if (
                    select_from_list(
                        ["Yes", "No"],
                        f"Play next: {selected_season.episodes[ep_idx+1].title}?",
                    )
                    == 0
                ):
                    ep_idx += 1
                    continue
            break
