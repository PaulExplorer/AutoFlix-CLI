from ..scraping import anime_sama, player
from ..cli_utils import (
    select_from_list,
    print_header,
    print_info,
    print_warning,
    print_success,
    print_error,
    get_user_input,
    console,
)
from ..player_manager import play_video
from ..tracker import tracker
from ..anilist import anilist_client
import re


def handle_anime_sama():
    """Handle Anime-Sama provider flow."""
    anime_sama.get_website_url()

    print_header("🎌 Anime-Sama")
    query = get_user_input("Search query")

    print_info(f"Searching for: [cyan]{query}[/cyan]")
    results = anime_sama.search(query)

    if not results:
        print_warning("No results found.")
        return

    choice_idx = select_from_list(
        [f"{r.title} ({', '.join(r.genres)})" for r in results], "📺 Search Results:"
    )
    selection = results[choice_idx]

    print_info(f"Loading [cyan]{selection.title}[/cyan]...")
    series = anime_sama.get_series(selection.url)

    if not series.seasons:
        print_warning("No seasons found.")
        return

    # Check for saved progress for this specific series
    saved_progress = tracker.get_series_progress("Anime-Sama", series.title)
    if saved_progress:
        choice = select_from_list(
            [
                f"Resume {saved_progress['season_title']} - {saved_progress['episode_title']}",
                "Browse Seasons",
            ],
            f"Found saved progress for {series.title}:",
        )
        if choice == 0:
            resume_anime_sama(saved_progress)
            return

    season_idx = select_from_list(
        [s.title for s in series.seasons], "📺 Select Season:"
    )
    selected_season_access = series.seasons[season_idx]

    print_info(f"Loading [cyan]{selected_season_access.title}[/cyan]...")
    season = anime_sama.get_season(selected_season_access.url)

    # episodes is dict {lang: [Episode]}
    langs = list(season.episodes.keys())
    if not langs:
        print_warning("No episodes found.")
        return

    lang_idx = select_from_list(langs, "🌍 Select Language:")
    selected_lang = langs[lang_idx]
    episodes = season.episodes[selected_lang]

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

        # Loop to allow retrying with another player
        playback_success = False
        while True:
            player_idx = select_from_list(
                [
                    f"{p.name} : {p.url.split('/')[2].split('.')[-2]}"
                    for p in supported_players
                ]
                + ["← Back"],
                "🎮 Select Player:",
            )

            if player_idx == len(supported_players):  # Back
                return

            success = play_video(
                supported_players[player_idx].url,
                headers={"Referer": anime_sama.website_origin},
                title=f"{series.title} - {season.title} - {selected_episode.title}",
            )

            if success:
                # Save progress
                tracker.save_progress(
                    provider="Anime-Sama",
                    series_title=series.title,
                    season_title=season.title,
                    episode_title=selected_episode.title,
                    series_url=series.url,
                    season_url=selected_season_access.url,
                    episode_url="",  # content.episode_url if available
                    logo_url=series.img,
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
            # --- AniList Progress Update ---
            anilist_token = tracker.get_anilist_token()
            if anilist_token:
                # Try to extract episode number
                episode_num = 1
                match = re.search(r"(\d+)", selected_episode.title)
                if match:
                    episode_num = int(match.group(1))

                # Check if we have a mapping
                media_id = tracker.get_anilist_mapping("Anime-Sama", series.title)

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
                            m_idx = select_from_list(
                                media_options, "Select AniList Match:"
                            )
                            if m_idx < len(results):
                                media_id = results[m_idx]["id"]
                                tracker.set_anilist_mapping(
                                    "Anime-Sama", series.title, media_id
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
                            if rel["relationType"] == "SEQUEL" and rel["node"][
                                "format"
                            ] in ["TV", "ONA", "MOVIE"]:
                                sequel = rel["node"]
                                break

                        if sequel:
                            sequel_title = (
                                sequel["title"]["english"] or sequel["title"]["romaji"]
                            )
                            print_info(f"Found sequel: [cyan]{sequel_title}[/cyan]")

                            if (
                                select_from_list(
                                    ["Yes", "No"],
                                    f"Switch AniList mapping to sequel '{sequel_title}'?",
                                )
                                == 0
                            ):
                                # Calculate new relative episode number?
                                # Usually sequels start at 1.
                                # If episodes are continuous (13, 14...), we might need to subtract total_eps.
                                # Let's ask user or assume relative?
                                # Safest is to calculate if large number.
                                new_ep_num = episode_num
                                if episode_num > total_eps:
                                    new_ep_num = episode_num - total_eps

                                print_info(
                                    f"Updating mapping to use Episode {new_ep_num} on new entry..."
                                )
                                tracker.set_anilist_mapping(
                                    "Anime-Sama", series.title, sequel["id"]
                                )
                                media_id = sequel["id"]
                                episode_num = new_ep_num

                    if anilist_client.update_progress(media_id, episode_num):
                        print_success("AniList updated!")
                    else:
                        print_error("Failed to update AniList.")

            if ep_idx + 1 < len(episodes):
                next_ep = episodes[ep_idx + 1]
                choice = select_from_list(
                    ["Yes", "No"], f"Play next episode: {next_ep.title}?"
                )
                if choice == 0:
                    ep_idx += 1
                    continue
            break


def resume_anime_sama(data):
    """Resume Anime-Sama playback."""
    print_info(f"Resuming [cyan]{data['series_title']}[/cyan]...")

    # We need to reload just the season to find the episode link/player
    # We have season_url saved.
    anime_sama.get_website_url()

    # Re-fetch season
    # Note: season_url might be absolute or relative.
    # tracker stores relative if we used _to_relative.
    # But for Anime-Sama it's scraping logic, let's see.
    # Anime-Sama URLs in tracker seem to be absolute because `get_series` returns absolute.
    # But `tracker.save_progress` calls `_to_relative`.
    # So we need to re-make absolute if needed.

    season_url = data["season_url"]
    if season_url.startswith("/") or not season_url.startswith("http"):
        # We need the base URL.
        # Ideally stored in tracker or re-fetched.
        season_url = anime_sama.website_origin.rstrip("/") + season_url

    print_info(f"Loading Season: {season_url}")
    try:
        season = anime_sama.get_season(season_url)
    except Exception as e:
        print_error(f"Could not load season: {e}")
        return

    langs = list(season.episodes.keys())
    if not langs:
        return

    # If only one language, pick it. If multiple, ask.
    if len(langs) == 1:
        selected_lang = langs[0]
    else:
        # Try to guess or ask?
        # Ideally we saved language. Since we didn't, we ask.
        lang_idx = select_from_list(langs, "🌍 Select Language:")
        selected_lang = langs[lang_idx]

    episodes = season.episodes[selected_lang]

    # Find the episode index
    start_ep_idx = 0
    saved_ep_title = data["episode_title"]

    for i, ep in enumerate(episodes):
        if ep.title == saved_ep_title:
            start_ep_idx = i
            break

    # Propose to continue (next episode) or watch again
    options = [
        (
            f"Continue (Next: {episodes[start_ep_idx+1].title})"
            if start_ep_idx + 1 < len(episodes)
            else "No next episode"
        ),
        f"Watch again ({saved_ep_title})",
        "Cancel",
    ]
    choice = select_from_list(options, "What would you like to do?")

    if choice == 2:  # Cancel
        return
    elif choice == 0:  # Continue
        if start_ep_idx + 1 < len(episodes):
            start_ep_idx += 1
        else:
            print_warning("No next episode found.")
            return
    # choice 1 is watch again -> keep start_ep_idx

    # Start loop
    ep_idx = start_ep_idx

    # Standard playback loop (copied from handle_anime_sama but simplified)
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

        playback_success = False
        while True:
            player_idx = select_from_list(
                [
                    f"{p.name} : {p.url.split('/')[2].split('.')[-2]}"
                    for p in supported_players
                ]
                + ["← Back"],
                "🎮 Select Player:",
            )

            if player_idx == len(supported_players):
                return

            success = play_video(
                supported_players[player_idx].url,
                headers={"Referer": anime_sama.website_origin},
                title=f"{data['series_title']} - {season.title} - {selected_episode.title}",
            )

            if success:
                tracker.save_progress(
                    provider="Anime-Sama",
                    series_title=data["series_title"],
                    season_title=season.title,
                    episode_title=selected_episode.title,
                    series_url=data["series_url"],
                    season_url=data["season_url"],
                    episode_url="",
                    logo_url=data.get("logo_url"),
                )
                playback_success = True
                break
            else:
                retry = select_from_list(
                    ["Try another server/player", "← Back to main menu"],
                    "What would you like to do?",
                )
                if retry == 1:
                    return

        if playback_success:
            # --- AniList Progress Update ---
            anilist_token = tracker.get_anilist_token()
            if anilist_token:
                # Try to extract episode number
                episode_num = 1
                match = re.search(r"(\d+)", selected_episode.title)
                if match:
                    episode_num = int(match.group(1))

                # Check if we have a mapping
                media_id = tracker.get_anilist_mapping(
                    "Anime-Sama", data["series_title"]
                )

                if not media_id:
                    # Ask user if they want to link (Logic copied from handle_anime_sama)
                    link_choice = select_from_list(
                        ["Yes", "No"],
                        f"Link '{data['series_title']}' to AniList for auto-tracking?",
                    )
                    if link_choice == 0:
                        results = anilist_client.search_media(data["series_title"])
                        if results:
                            media_options = [
                                f"{m['title']['english'] or m['title']['romaji']} ({m['seasonYear']})"
                                for m in results
                            ] + ["Cancel"]
                            m_idx = select_from_list(
                                media_options, "Select AniList Match:"
                            )
                            if m_idx < len(results):
                                media_id = results[m_idx]["id"]
                                tracker.set_anilist_mapping(
                                    "Anime-Sama", data["series_title"], media_id
                                )
                                print_success(
                                    f"Linked to {results[m_idx]['title']['english'] or results[m_idx]['title']['romaji']}!"
                                )

                if media_id:
                    # Update progress with overflow detection
                    print_info(f"Updating AniList to episode {episode_num}...")
                    anilist_client.set_token(anilist_token)

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

                        sequel = None
                        relations = media_details.get("relations", {}).get("edges", [])
                        for rel in relations:
                            if rel["relationType"] == "SEQUEL" and rel["node"][
                                "format"
                            ] in ["TV", "ONA", "MOVIE"]:
                                sequel = rel["node"]
                                break

                        if sequel:
                            sequel_title = (
                                sequel["title"]["english"] or sequel["title"]["romaji"]
                            )
                            print_info(f"Found sequel: [cyan]{sequel_title}[/cyan]")

                            if (
                                select_from_list(
                                    ["Yes", "No"],
                                    f"Switch AniList mapping to sequel '{sequel_title}'?",
                                )
                                == 0
                            ):
                                new_ep_num = episode_num
                                if episode_num > total_eps:
                                    new_ep_num = episode_num - total_eps

                                print_info(
                                    f"Updating mapping to use Episode {new_ep_num} on new entry..."
                                )
                                tracker.set_anilist_mapping(
                                    "Anime-Sama", data["series_title"], sequel["id"]
                                )
                                media_id = sequel["id"]
                                episode_num = new_ep_num

                    if anilist_client.update_progress(media_id, episode_num):
                        print_success("AniList updated!")
                    else:
                        print_error("Failed to update AniList.")

            if ep_idx + 1 < len(episodes):
                next_ep = episodes[ep_idx + 1]
                choice = select_from_list(
                    ["Yes", "No"], f"Play next episode: {next_ep.title}?"
                )
                if choice == 0:
                    ep_idx += 1
                    continue
            break
