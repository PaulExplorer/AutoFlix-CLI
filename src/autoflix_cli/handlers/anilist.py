from ..anilist import anilist_client
from ..tracker import tracker
from ..cli_utils import (
    select_from_list,
    print_info,
    print_warning,
    print_error,
    get_user_input,
)
from .anime_sama import anime_sama


def handle_anilist_continue():
    """Handle the 'Continue from AniList' flow."""
    token = tracker.get_anilist_token()
    if not token:
        print_error("Please configure your AniList token in Settings > AniList first.")
        return

    anilist_client.set_token(token)
    print_info("Fetching your watching list from AniList...")

    # Needs user ID first
    user = anilist_client.validate_token()
    if not user:
        print_error("Invalid AniList token.")
        return

    entries = anilist_client.get_user_watching(user["id"])
    if not entries:
        print_warning("No anime currently watching found on AniList.")
        return

    # Create display options
    display_options = []
    for e in entries:
        title = e["media"]["title"]["english"] or e["media"]["title"]["romaji"]
        progress = e["progress"] or 0
        total = e["media"]["episodes"] or "?"
        display_options.append(f"{title} (Ep {progress+1}/{total})")

    display_options.append("← Back")

    choice_idx = select_from_list(display_options, "Select Anime to Continue:")
    if choice_idx == len(entries):  # Back
        return

    selected_entry = entries[choice_idx]
    media_title = (
        selected_entry["media"]["title"]["english"]
        or selected_entry["media"]["title"]["romaji"]
    )
    media_id = selected_entry["mediaId"]
    next_episode_num = (selected_entry["progress"] or 0) + 1

    print_info(f"Target: [cyan]{media_title}[/cyan] - Episode {next_episode_num}")

    # Check for existing mapping to avoid re-searching if verified
    # Current mapping structure is Provider|SeriesTitle -> MediaId
    # It's one-way currently, we need to iterate or search.
    # For now, let's search provider blindly or improve tracker map later.
    # Actually, we can just search Anime-Sama directly.

    anime_sama.get_website_url()

    print_info(f"Searching for '{media_title}' on Anime-Sama...")
    results = anime_sama.search(media_title)

    # Fallback 1: Try Romaji if English failed and they are different
    romaji_title = selected_entry["media"]["title"]["romaji"]
    if not results and romaji_title and romaji_title != media_title:
        print_warning(
            f"No results for English title. Trying Romaji: '{romaji_title}'..."
        )
        results = anime_sama.search(romaji_title)

    # Fallback 2: Manual Search
    if not results:
        print_warning("No results found on Anime-Sama.")
        choice = select_from_list(
            ["Try Manual Search", "Cancel"], "What would you like to do?"
        )
        if choice == 0:
            manual_query = get_user_input("Enter search query")
            results = anime_sama.search(manual_query)
            if not results:
                print_error("Still no results found.")
                return
        else:
            return

    # Let user confirm the match to be safe
    r_idx = select_from_list(
        [r.title for r in results] + ["Cancel"], "Select the matching result:"
    )
    if r_idx == len(results):
        return

    selection = results[r_idx]

    # Save mapping for future (Reverse mapping: MediaID -> ProviderSeriesTitle is needed or just rely on search)
    # The current mapping in tracker is Provider|SeriesTitle -> MediaID.
    # Since we found it, we can ensure the mapping exists if not already.
    # But wait, we searched for it. We can save it.
    tracker.set_anilist_mapping("Anime-Sama", selection.title, media_id)

    # Now just use the Anime-Sama handler logic but bypass search?
    # Or just jump into getting series...

    print_info(f"Loading [cyan]{selection.title}[/cyan]...")
    series = anime_sama.get_series(selection.url)

    if not series.seasons:
        print_warning("No seasons found.")
        return

    # ... logic continues similar to handle_anime_sama but targeted ...
    # Simplified flow for now: Just show seasons.

    season_idx = select_from_list(
        [s.title for s in series.seasons], "📺 Select Season:"
    )
    selected_season_access = series.seasons[season_idx]

    print_info(f"Loading [cyan]{selected_season_access.title}[/cyan]...")
    season = anime_sama.get_season(selected_season_access.url)

    langs = list(season.episodes.keys())
    if not langs:
        print_warning("No episodes found.")
        return

    lang_idx = select_from_list(langs, "🌍 Select Language:")
    selected_lang = langs[lang_idx]
    episodes = season.episodes[selected_lang]

    # Find target episode
    start_ep_idx = 0
    # Try to find by number (often title contains number)
    # This is rough, regex search for next_episode_num
    import re

    found = False
    for i, ep in enumerate(episodes):
        match = re.search(r"(\d+)", ep.title)
        if match and int(match.group(1)) == next_episode_num:
            start_ep_idx = i
            found = True
            break

    if not found:
        print_warning(
            f"Could not automatically find Episode {next_episode_num}. Please select:"
        )
        start_ep_idx = select_from_list(
            [e.title for e in episodes], "📺 Select Episode:"
        )
    else:
        print_success(
            f"Found Episode {next_episode_num}: {episodes[start_ep_idx].title}"
        )

    # Start playback from there...
    # We can reuse the loop logic or create a helper.
    # Since we are in handlers, maybe valid to reuse code?
    # Or strict DRY.
    # For now, let's copy the playback loop to ensure stability.

    ep_idx = start_ep_idx
    from ..player_manager import play_video
    from ..scraping import player

    while True:
        selected_episode = episodes[ep_idx]
        if not selected_episode.players:
            return

        supported = [p for p in selected_episode.players if player.is_supported(p.url)]
        if not supported:
            print_warning("No supported players found.")
            return

        playback_success = False
        while True:
            player_idx = select_from_list(
                [f"{p.name}" for p in supported] + ["← Back"], "🎮 Select Player:"
            )
            if player_idx == len(supported):
                return

            success = play_video(
                supported[player_idx].url,
                headers={"Referer": anime_sama.website_origin},
                title=f"{series.title} - {season.title} - {selected_episode.title}",
            )

            if success:
                tracker.save_progress(
                    provider="Anime-Sama",
                    series_title=series.title,
                    season_title=season.title,
                    episode_title=selected_episode.title,
                    series_url=series.url,
                    season_url=selected_season_access.url,
                    episode_url="",
                    logo_url=series.img,
                )
                playback_success = True
                break
            else:
                if select_from_list(["Retry", "Back"], "Action?") == 1:
                    return

        if playback_success:
            # Auto update AniList since we are in AniList mode!
            print_info(f"Updating AniList to episode {next_episode_num}...")
            # Recalculate episode num from title just in case user changed episode
            match = re.search(r"(\d+)", selected_episode.title)
            if match:
                current_ep_num = int(match.group(1))
                if anilist_client.update_progress(media_id, current_ep_num):
                    print_success("AniList updated!")

            if ep_idx + 1 < len(episodes):
                if (
                    select_from_list(
                        ["Yes", "No"], f"Play next: {episodes[ep_idx+1].title}?"
                    )
                    == 0
                ):
                    ep_idx += 1
                    # Update local next_episode_num for next loop AniList update?
                    # The loop recalculates it from title.
                    continue
            break
