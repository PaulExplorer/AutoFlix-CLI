from ..scraping import arkanime, player
from ..scraping.objects import ArkMovie, ArkSeries
from ..cli_utils import (
    select_from_list,
    print_success,
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
from .anilist_update import _update_anilist_progress


def handle_arkanime():
    """Handle ArkAnime provider flow."""
    arkanime.get_website_url()

    print_header("⛩️ ArkAnime")

    while True:
        query = get_user_input("Search query (or 'exit' to back)")
        if not query or query.lower() == "exit":
            break

        print_info(f"Searching for: [cyan]{query}[/cyan]")
        try:
            results = arkanime.search(query)
        except Exception as e:
            print_error(f"Error searching: {e}")
            pause()
            continue

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
            content = arkanime.get_content(selection.url)
        except Exception as e:
            print_error(f"Error loading content: {e}")
            pause()
            continue

        if isinstance(content, ArkMovie):
            console.print(f"\n[bold]🎬 Movie:[/bold] [cyan]{content.title}[/cyan]\n")

            saved_progress = tracker.get_series_progress("ArkAnime", content.title)
            if saved_progress:
                choice = select_from_list(
                    ["Watch again/Resume", "Cancel"],
                    f"Found saved progress for {content.title}:",
                )
                if choice == 0:
                    resume_arkanime(saved_progress)
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

            headers = {"Referer": arkanime.website_origin}
            play_episode_flow(
                provider_name="ArkAnime",
                series_title=content.title,
                season_title="Movie",
                episode=content,
                series_url=content.id,
                season_url=content.id,
                logo_url=content.img,
                headers=headers,
            )
            continue

        series = content

        if not series.seasons:
            print_warning("No seasons found.")
            pause()
            continue

        # Check for saved progress for this specific series
        saved_progress = tracker.get_series_progress("ArkAnime", series.title)
        if saved_progress:
            choice = select_from_list(
                [
                    f"Resume {saved_progress['season_title']} - {saved_progress['episode_title']}",
                    "Browse Seasons",
                    "← Cancel",
                ],
                f"Found saved progress for {series.title}:",
            )
            if choice == 0:
                resume_arkanime(saved_progress)
                continue
            if choice == 2:
                continue

        season_options = [s.title for s in series.seasons] + ["← Back"]
        season_idx = select_from_list(season_options, "📺 Select Season:")
        if season_idx == len(series.seasons):
            continue
        season = series.seasons[season_idx]

        if not season.episodes:
            print_warning("No episodes found.")
            pause()
            continue

        ep_options = [e.title for e in season.episodes] + ["← Back"]
        ep_idx = select_from_list(ep_options, "📺 Select Episode:")
        if ep_idx == len(season.episodes):
            continue

        while True:
            selected_episode = season.episodes[ep_idx]
            headers = {"Referer": arkanime.website_origin}

            success = play_episode_flow(
                provider_name="ArkAnime",
                series_title=series.title,
                season_title=season.title,
                episode=selected_episode,
                series_url=series.id,  # using id for url since we matched it
                season_url=str(season.id), # Using id for season url
                logo_url=series.img,
                headers=headers,
                anilist_callback=lambda: _update_anilist_progress(
                    "ArkAnime", series, season, selected_episode
                ),
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
                break


def resume_arkanime(data):
    """Resume ArkAnime playback."""
    arkanime.get_website_url()

    print_info(f"Resuming [cyan]{data['series_title']}[/cyan]...")

    try:
        content = arkanime.get_content(data["series_url"])
    except Exception as e:
        print_error(f"Could not load content: {e}")
        pause()
        return

    if isinstance(content, ArkMovie) or data.get("season_title") == "Movie":
        if not isinstance(content, ArkMovie):
            print_error("Expected a Movie but got something else.")
            pause()
            return

        options = ["Watch again", "Cancel"]
        choice = select_from_list(options, "What would you like to do?")

        if choice == 1:
            return

        headers = {"Referer": arkanime.website_origin}
        play_episode_flow(
            provider_name="ArkAnime",
            series_title=content.title,
            season_title="Movie",
            episode=content,
            series_url=content.id,
            season_url=content.id,
            logo_url=content.img,
            headers=headers,
        )
        return

    series = content

    season = None
    for s in series.seasons:
        if str(s.id) == data.get("season_url") or s.title == data.get("season_title"):
            season = s
            break

    if not season:
        print_error("Could not find the saved season.")
        pause()
        return

    if not season.episodes:
        print_warning("No episodes found in season.")
        pause()
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

    # Create dummy series object for callback
    class SeriesDummy:
        def __init__(self, t):
            self.title = t

    series_dummy = SeriesDummy(data["series_title"])

    while True:
        selected_episode = season.episodes[ep_idx]
        headers = {"Referer": arkanime.website_origin}

        success = play_episode_flow(
            provider_name="ArkAnime",
            series_title=data["series_title"],
            season_title=season.title,
            episode=selected_episode,
            series_url=data["series_url"],
            season_url=str(season.id),
            logo_url=data.get("logo_url"),
            headers=headers,
            anilist_callback=lambda: _update_anilist_progress(
                "ArkAnime", series_dummy, season, selected_episode
            ),
        )

        if success:
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
        else:
            return
