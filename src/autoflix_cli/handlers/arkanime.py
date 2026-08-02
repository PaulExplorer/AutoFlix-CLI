from ..scraping import arkanime, player
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
from ..anilist import anilist_client
import re


def _update_anilist_progress(series, season, selected_episode):
    # --- AniList Progress Update ---
    anilist_token = tracker.get_anilist_token()
    if not anilist_token:
        return

    # Try to extract episode number
    episode_num = 1
    match = re.search(r"(\d+)", selected_episode.title)
    if match:
        episode_num = int(match.group(1))

    # Check if we have a mapping
    media_id = tracker.get_anilist_mapping("ArkAnime", series.title, season.title)

    if not media_id:
        # Ask user if they want to link
        link_choice = select_from_list(
            ["Yes", "No"],
            f"Link '{series.title}' to AniList for auto-tracking?",
        )
        if link_choice == 0:
            results = anilist_client.search_media(series.title)
            if results:
                media_options = [
                    f"{m['title']['english'] or m['title']['romaji']} ({m['seasonYear']})"
                    for m in results
                ] + ["Cancel"]
                m_idx = select_from_list(media_options, "Select AniList Match:")
                if m_idx < len(results):
                    media_id = results[m_idx]["id"]
                    tracker.set_anilist_mapping(
                        "ArkAnime", series.title, media_id, season.title
                    )
                    print_success(
                        f"Linked to {results[m_idx]['title']['english'] or results[m_idx]['title']['romaji']}!"
                    )
            else:
                print_warning("No matches found on AniList.")

    if media_id:
        # Update progress with overflow detection
        print_info(f"Updating AniList to episode {episode_num}...")
        anilist_client.set_token(anilist_token)

        # Fetch media details to check total episodes
        media_details = anilist_client.get_media_with_relations(media_id)

        if (
            media_details
            and media_details.get("episodes")
            and episode_num > media_details["episodes"]
        ):
            total_eps = media_details["episodes"]
            print_warning(
                f"Episode {episode_num} exceeds max episodes ({total_eps}) for this AniList entry."
            )

            # Check for SEQUEL relation
            sequel = None
            relations = media_details.get("relations", {}).get("edges", [])
            for rel in relations:
                if rel["relationType"] == "SEQUEL" and rel["node"]["format"] in [
                    "TV",
                    "ONA",
                    "MOVIE",
                ]:
                    sequel = rel["node"]
                    break

            if sequel:
                sequel_title = sequel["title"]["english"] or sequel["title"]["romaji"]
                print_info(f"Found sequel: [cyan]{sequel_title}[/cyan]")

                if (
                    select_from_list(
                        ["Yes", "No"],
                        f"Switch AniList mapping to sequel '{sequel_title}'?",
                    )
                    == 0
                ):
                    # Calculate new relative episode number?
                    new_ep_num = episode_num
                    if episode_num > total_eps:
                        new_ep_num = episode_num - total_eps

                    print_info(
                        f"Updating mapping to use Episode {new_ep_num} on new entry..."
                    )
                    tracker.set_anilist_mapping(
                        "ArkAnime", series.title, sequel["id"], season.title
                    )
                    media_id = sequel["id"]
                    episode_num = new_ep_num

        if anilist_client.update_progress(media_id, episode_num):
            print_success("AniList updated!")
        else:
            print_error("Failed to update AniList.")

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
            series = arkanime.get_content(selection.url)
        except Exception as e:
            print_error(f"Error loading series: {e}")
            pause()
            continue

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
                ],
                f"Found saved progress for {series.title}:",
            )
            if choice == 0:
                resume_arkanime(saved_progress)
                continue

        season_idx = select_from_list(
            [s.title for s in series.seasons], "📺 Select Season:"
        )
        season = series.seasons[season_idx]

        if not season.episodes:
            print_warning("No episodes found.")
            pause()
            continue

        ep_idx = select_from_list(
            [e.title for e in season.episodes], "📺 Select Episode:"
        )

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
                    series, season, selected_episode
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
        series = arkanime.get_content(data["series_url"])
    except Exception as e:
        print_error(f"Could not load series: {e}")
        pause()
        return

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
                series_dummy, season, selected_episode
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
