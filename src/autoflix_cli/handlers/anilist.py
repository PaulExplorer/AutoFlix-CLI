from ..anilist import anilist_client
from ..tracker import tracker
import re
from ..cli_utils import (
    select_from_list,
    print_info,
    print_warning,
    print_error,
    print_success,
    get_user_input,
    clean_title,
    clear_screen,
    print_header,
)
from . import anime_sama as anime_sama_handler
from ..scraping import anime_sama as anime_sama_scraper
from . import goldenanime
from . import arkanime as arkanime_handler
from ..scraping import arkanime as arkanime_scraper
from .playback import play_episode_flow
from ..player_manager import play_video
from ..scraping import player
from ..scraping.objects import ArkMovie


def handle_anilist_continue():
    """Handle the 'Continue from AniList' flow - main menu."""
    token = tracker.get_anilist_token()
    if not token:
        print_error("Please configure your AniList token in Settings > AniList first.")
        return

    anilist_client.set_token(token)
    user = anilist_client.validate_token()
    if not user:
        print_error("Invalid AniList token.")
        return

    while True:
        clear_screen()
        print_header("📋 AniList Lists")

        opts = [
            "▶ Continue Watching (CURRENT)",
            "📅 Planning / To Watch (PLANNING)",
            "✅ Completed (COMPLETED)",
            "❌ Dropped (DROPPED)",
            "← Back to Main Menu",
        ]

        choice = select_from_list(opts, "Select List to Browse:")

        if choice == 0:
            _browse_anilist_list(user["id"], "CURRENT", "Continue Watching")
        elif choice == 1:
            _browse_anilist_list(user["id"], "PLANNING", "Planning")
        elif choice == 2:
            _browse_anilist_list(user["id"], "COMPLETED", "Completed")
        elif choice == 3:
            _browse_anilist_list(user["id"], "DROPPED", "Dropped")
        else:
            break


def _browse_anilist_list(user_id: int, status: str, display_name: str):
    """Browse and interact with an AniList list (CURRENT, PLANNING, COMPLETED, DROPPED)."""
    print_info(f"Fetching your {display_name.lower()} list from AniList...")
    entries = anilist_client.get_user_list(user_id, status)
    
    if not entries:
        print_warning(f"No anime found in {display_name}.")
        from ..cli_utils import pause
        pause()
        return

    while True:
        clear_screen()
        print_header(f"📋 {display_name}")

        display_options = []
        for e in entries:
            title = e["media"]["title"]["english"] or e["media"]["title"]["romaji"]
            progress = e["progress"] or 0
            total = e["media"]["episodes"] or "?"
            score = e.get("score")
            
            # Calculate latest released episode & episodes behind (like before)
            next_airing = e["media"].get("nextAiringEpisode")
            latest_released = None
            if next_airing and isinstance(next_airing, dict) and next_airing.get("episode"):
                latest_released = max(0, next_airing["episode"] - 1)
            elif isinstance(e["media"].get("episodes"), int):
                latest_released = e["media"]["episodes"]

            if isinstance(total, int) and progress >= total:
                status_info = f"Finished {progress}/{total}"
            else:
                status_info = f"Ep {progress+1}/{total}" if isinstance(total, int) else f"Ep {progress+1}/?"

            if latest_released is not None:
                behind = max(0, latest_released - progress)
                if behind > 0:
                    status_info += f" - {behind} ep behind"
                else:
                    status_info += " - Up to date"
            
            if score:
                status_info += f" - ⭐ {score}/100"

            display_options.append(f"{title} ({status_info})")

        display_options.append("← Back")

        choice_idx = select_from_list(display_options, f"Select Anime ({display_name}):")
        if choice_idx == len(entries):  # Back
            # Refresh entries in case something changed
            entries = anilist_client.get_user_list(user_id, status)
            return

        selected_entry = entries[choice_idx]
        _handle_entry_actions(user_id, selected_entry, status, entries)
        
        # After action, refresh the list
        entries = anilist_client.get_user_list(user_id, status)


def _handle_entry_actions(user_id: int, entry: dict, current_status: str, entries: list):
    """Handle actions for a selected AniList entry."""
    media = entry["media"]
    media_title = media["title"]["english"] or media["title"]["romaji"]
    media_id = entry["mediaId"]
    progress = entry["progress"] or 0
    total = media["episodes"] or "?"
    
    while True:
        clear_screen()
        print_header(f"📺 {media_title}")
        
        status_display = {
            "CURRENT": "🟢 Currently Watching",
            "PLANNING": "📅 Planning",
            "COMPLETED": "✅ Completed",
            "DROPPED": "❌ Dropped",
            "PAUSED": "⏸️ Paused",
        }.get(current_status, current_status)
        
        print_info(f"Status: {status_display}")
        print_info(f"Progress: {progress}/{total}" if isinstance(total, int) else f"Progress: {progress}/{total}")
        if entry.get("score"):
            print_info(f"Score: {entry['score']}/100")

        # Build action menu based on current status
        actions = []
        
        if current_status == "CURRENT":
            actions = [
                "▶ Continue Watching",
                "✅ Mark as Completed",
                "❌ Mark as Dropped",
                "⏸️ Mark as Paused",
                "🔄 Update Progress",
                "← Back to List",
            ]
        elif current_status == "PLANNING":
            actions = [
                "▶ Start Watching (mark as CURRENT)",
                "✅ Mark as Completed",
                "❌ Mark as Dropped",
                "🗑️ Remove from List",
                "← Back to List",
            ]
        elif current_status == "COMPLETED":
            actions = [
                "🔄 Rewatch (mark as CURRENT)",
                "❌ Mark as Dropped",
                "🗑️ Remove from List",
                "← Back to List",
            ]
        elif current_status == "DROPPED":
            actions = [
                "▶ Give Another Try (mark as CURRENT)",
                "📅 Move to Planning",
                "🗑️ Remove from List",
                "← Back to List",
            ]
        else:
            actions = [
                "🗑️ Remove from List",
                "← Back to List",
            ]

        action_idx = select_from_list(actions, "Action:")

        # --- CURRENT actions ---
        if current_status == "CURRENT":
            if action_idx == 0:  # Continue Watching
                _continue_watching_entry(user_id, entry)
                return  # Go back to main AniList menu after watching
            elif action_idx == 1:  # Mark Completed
                if anilist_client.update_status(media_id, "COMPLETED", total if isinstance(total, int) else progress):
                    print_success("Marked as Completed!")
                else:
                    print_error("Failed to update status.")
                from ..cli_utils import pause
                pause()
                return
            elif action_idx == 2:  # Mark Dropped
                if anilist_client.update_status(media_id, "DROPPED", progress):
                    print_success("Marked as Dropped!")
                else:
                    print_error("Failed to update status.")
                from ..cli_utils import pause
                pause()
                return
            elif action_idx == 3:  # Mark Paused
                if anilist_client.update_status(media_id, "PAUSED", progress):
                    print_success("Marked as Paused!")
                else:
                    print_error("Failed to update status.")
                from ..cli_utils import pause
                pause()
                return
            elif action_idx == 4:  # Update Progress
                new_progress = get_user_input(f"New episode number (current: {progress})")
                if new_progress and new_progress.isdigit():
                    new_progress = int(new_progress)
                    if anilist_client.update_status(media_id, "CURRENT", new_progress):
                        print_success(f"Progress updated to episode {new_progress}!")
                    else:
                        print_error("Failed to update progress.")
                else:
                    print_error("Invalid number or cancelled.")
                from ..cli_utils import pause
                pause()
            else:  # Back
                return

        # --- PLANNING actions ---
        elif current_status == "PLANNING":
            if action_idx == 0:  # Start Watching
                if anilist_client.update_status(media_id, "CURRENT", 0):
                    print_success("Moved to Currently Watching!")
                    _continue_watching_entry(user_id, entry)
                    return
                else:
                    print_error("Failed to update status.")
                    from ..cli_utils import pause
                    pause()
            elif action_idx == 1:  # Mark Completed
                if anilist_client.update_status(media_id, "COMPLETED", total if isinstance(total, int) else 1):
                    print_success("Marked as Completed!")
                else:
                    print_error("Failed to update status.")
                from ..cli_utils import pause
                pause()
                return
            elif action_idx == 2:  # Mark Dropped
                if anilist_client.update_status(media_id, "DROPPED", 0):
                    print_success("Marked as Dropped!")
                else:
                    print_error("Failed to update status.")
                from ..cli_utils import pause
                pause()
                return
            elif action_idx == 3:  # Remove from List
                if anilist_client.remove_from_list(media_id):
                    print_success("Removed from list!")
                else:
                    print_error("Failed to remove from list.")
                from ..cli_utils import pause
                pause()
                return
            else:  # Back
                return

        # --- COMPLETED actions ---
        elif current_status == "COMPLETED":
            if action_idx == 0:  # Rewatch
                if anilist_client.update_status(media_id, "CURRENT", 0):
                    print_success("Moved to Currently Watching for rewatch!")
                    _continue_watching_entry(user_id, entry)
                    return
                else:
                    print_error("Failed to update status.")
                    from ..cli_utils import pause
                    pause()
            elif action_idx == 1:  # Mark Dropped
                if anilist_client.update_status(media_id, "DROPPED", total if isinstance(total, int) else progress):
                    print_success("Marked as Dropped!")
                else:
                    print_error("Failed to update status.")
                from ..cli_utils import pause
                pause()
                return
            elif action_idx == 2:  # Remove from List
                if anilist_client.remove_from_list(media_id):
                    print_success("Removed from list!")
                else:
                    print_error("Failed to remove from list.")
                from ..cli_utils import pause
                pause()
                return
            else:  # Back
                return

        # --- DROPPED actions ---
        elif current_status == "DROPPED":
            if action_idx == 0:  # Give Another Try
                if anilist_client.update_status(media_id, "CURRENT", progress):
                    print_success("Moved to Currently Watching!")
                    _continue_watching_entry(user_id, entry)
                    return
                else:
                    print_error("Failed to update status.")
                    from ..cli_utils import pause
                    pause()
            elif action_idx == 1:  # Move to Planning
                if anilist_client.update_status(media_id, "PLANNING", progress):
                    print_success("Moved to Planning!")
                else:
                    print_error("Failed to update status.")
                from ..cli_utils import pause
                pause()
                return
            elif action_idx == 2:  # Remove from List
                if anilist_client.remove_from_list(media_id):
                    print_success("Removed from list!")
                else:
                    print_error("Failed to remove from list.")
                from ..cli_utils import pause
                pause()
                return
            else:  # Back
                return
        else:
            if action_idx == 0:  # Remove from List
                if anilist_client.remove_from_list(media_id):
                    print_success("Removed from list!")
                else:
                    print_error("Failed to remove from list.")
                from ..cli_utils import pause
                pause()
                return
            else:  # Back
                return


def _continue_watching_entry(user_id: int, entry: dict):
    """Launch the provider selection and playback flow for an entry."""
    media = entry["media"]
    media_title = media["title"]["english"] or media["title"]["romaji"]
    media_id = entry["mediaId"]
    progress = entry["progress"] or 0
    total = media["episodes"] or "?"
    next_episode_num = progress + 1
    romaji_title = media["title"]["romaji"]

    if isinstance(total, int) and progress >= total:
        print_info(
            f"Target: [cyan]{media_title}[/cyan] - [yellow]Completed ({progress}/{total})[/yellow]"
        )
        next_episode_num = progress
    else:
        print_info(f"Target: [cyan]{media_title}[/cyan] - Episode {next_episode_num}")

    # --- Provider Selection ---
    providers = ["Anime-Sama (VF/VOSTFR)", "GoldenAnime (VO)", "⛩️ ArkAnime (Anime & Animations)", "← Back"]
    p_choice = select_from_list(providers, "Select Provider:")

    if p_choice == 3:  # Back
        return

    # Extract cover URL
    cover_url = media.get("coverImage", {}).get(
        "large"
    ) or media.get("coverImage", {}).get("medium")

    if p_choice == 1:  # GoldenAnime
        goldenanime.handle_goldenanime_episode(
            title=media_title,
            anilist_id=media_id,
            start_episode=next_episode_num,
            cover_url=cover_url,
        )
        return

    if p_choice == 2:  # ArkAnime
        content = _search_and_select_series(arkanime_scraper, media_title, romaji_title)
        if not content:
            return

        if isinstance(content, ArkMovie):
            if not content.players:
                print_warning("No players found.")
                return
            play_episode_flow(
                provider_name="ArkAnime",
                series_title=content.title,
                season_title="Movie",
                episode=content,
                series_url=content.id,
                season_url=content.id,
                logo_url=content.img,
                headers={"Referer": arkanime_scraper.website_origin},
            )
            return

        series = content
        if not series.seasons:
            print_warning("No seasons found.")
            return

        season = _auto_select_season(series.seasons, media_title, romaji_title)
        if not season:
            return
        tracker.set_anilist_mapping("ArkAnime", series.title, media_id, season.title)

        episodes = season.episodes
        if not episodes:
            print_warning("No episodes found.")
            return

        start_ep_idx = _auto_select_episode(episodes, next_episode_num)
        if start_ep_idx is None:
            return
        
        class SeriesDummy:
            def __init__(self, t): self.title = t
        series_dummy = SeriesDummy(series.title)

        ep_idx = start_ep_idx
        while True:
            selected_episode = episodes[ep_idx]
            success = play_episode_flow(
                provider_name="ArkAnime",
                series_title=series.title,
                season_title=season.title,
                episode=selected_episode,
                series_url=series.id,
                season_url=str(season.id),
                logo_url=series.img,
                headers={"Referer": arkanime_scraper.website_origin},
                anilist_callback=lambda: arkanime_handler._update_anilist_progress(
                    "ArkAnime", series_dummy, season, selected_episode
                ),
            )
            if success and ep_idx + 1 < len(episodes):
                if select_from_list(["Yes", "No"], f"Play next: {episodes[ep_idx+1].title}?") == 0:
                    ep_idx += 1
                    continue
            break

    else:  # Anime-Sama
        series = _search_and_select_series(anime_sama_scraper, media_title, romaji_title)
        if not series or not series.seasons:
            if series and not series.seasons:
                print_warning("No seasons found.")
            return

        selected_season_access = _auto_select_season(series.seasons, media_title, romaji_title)
        if not selected_season_access:
            return
        
        print_info(f"Loading [cyan]{selected_season_access.title}[/cyan]...")
        season = anime_sama_scraper.get_season(selected_season_access.url)
        tracker.set_anilist_mapping("Anime-Sama", series.title, media_id, season.title)

        langs = list(season.episodes.keys())
        if not langs:
            print_warning("No episodes found.")
            return
            
        lang_idx = select_from_list(langs + ["← Back"], "🌍 Select Language:")
        if lang_idx == len(langs):
            return
        episodes = season.episodes[langs[lang_idx]]

        start_ep_idx = _auto_select_episode(episodes, next_episode_num)
        if start_ep_idx is None:
            return

        class SeriesDummy:
            def __init__(self, t): self.title = t
        series_dummy = SeriesDummy(series.title)

        ep_idx = start_ep_idx
        while True:
            selected_episode = episodes[ep_idx]
            success = play_episode_flow(
                provider_name="Anime-Sama",
                series_title=series.title,
                season_title=season.title,
                episode=selected_episode,
                series_url=series.url,
                season_url=selected_season_access.url,
                logo_url=series.img,
                headers={"Referer": anime_sama_scraper.website_origin},
                anilist_callback=lambda: anime_sama_handler._update_anilist_progress(
                    "Anime-Sama", series_dummy, season, selected_episode
                ),
            )
            if success and ep_idx + 1 < len(episodes):
                if select_from_list(["Yes", "No"], f"Play next: {episodes[ep_idx+1].title}?") == 0:
                    ep_idx += 1
                    continue
            break


def _search_and_select_series(scraper, media_title, romaji_title):
    scraper.get_website_url()
    cleaned_title = clean_title(media_title)
    
    # Try to extract a clean name for printing without 'autoflix_cli.scraping.'
    scraper_name = scraper.__name__.split('.')[-1]
    if scraper_name == "anime_sama": scraper_name = "Anime-Sama"
    elif scraper_name == "arkanime": scraper_name = "ArkAnime"
    
    print_info(f"Searching for '{media_title}' on {scraper_name}...")
    results = scraper.search(media_title)

    if not results and cleaned_title != media_title:
        print_info(f"No results for full title. Trying cleaned: '{cleaned_title}'...")
        results = scraper.search(cleaned_title)

    if not results and romaji_title and romaji_title != media_title:
        print_warning(f"No results for English title. Trying Romaji: '{romaji_title}'...")
        results = scraper.search(romaji_title)
        if not results:
            cleaned_romaji = clean_title(romaji_title)
            if cleaned_romaji != romaji_title:
                print_info(f"Trying cleaned Romaji: '{cleaned_romaji}'...")
                results = scraper.search(cleaned_romaji)

    if not results:
        print_warning(f"No results found on {scraper_name}.")
        choice = select_from_list(["Try Manual Search", "Cancel"], "What would you like to do?")
        if choice == 0:
            manual_query = get_user_input("Enter search query")
            results = scraper.search(manual_query)
            if not results:
                print_error("Still no results found.")
                return None
        else:
            return None

    r_idx = select_from_list([r.title for r in results] + ["Cancel"], "Select the matching result:")
    if r_idx == len(results):
        return None

    selection = results[r_idx]
    print_info(f"Loading [cyan]{selection.title}[/cyan]...")
    if hasattr(scraper, "get_content"):
        return scraper.get_content(selection.url)
    return scraper.get_series(selection.url)


def _auto_select_season(series_seasons, media_title, romaji_title):
    target_season_num = None
    for t in [media_title, romaji_title]:
        if not t: continue
        match = re.search(r"Season\s+(\d+)", t, re.IGNORECASE)
        if match:
            target_season_num = int(match.group(1))
            break
        match = re.search(r"\s+S(\d+)", t, re.IGNORECASE)
        if match:
            target_season_num = int(match.group(1))
            break

    if target_season_num is None:
        for t in [media_title, romaji_title]:
            if not t: continue
            match = re.search(r"Part\s+(\d+)", t, re.IGNORECASE)
            if match:
                target_season_num = int(match.group(1))
                break

    default_season_idx = 0
    if target_season_num is not None:
        for i, s in enumerate(series_seasons):
            s_match = re.search(r"(?:Saison|Season)\s+(\d+)", s.title, re.IGNORECASE)
            if s_match and int(s_match.group(1)) == target_season_num:
                default_season_idx = i
                break
            if target_season_num == 1 and "Saison" not in s.title and "Season" not in s.title:
                if len(series_seasons) == 1:
                    default_season_idx = 0
                    break

    season_idx = select_from_list(
        [s.title for s in series_seasons] + ["← Back"],
        "📺 Select Season:",
        default_index=default_season_idx,
    )

    if season_idx == len(series_seasons):
        return None

    if target_season_num is not None:
        print_info(f"AniList suggests [bold]Season {target_season_num}[/bold].")
    
    return series_seasons[season_idx]


def _auto_select_episode(episodes, next_episode_num):
    start_ep_idx = 0
    found = False
    for i, ep in enumerate(episodes):
        match = re.search(r"(\d+)", ep.title)
        if match and int(match.group(1)) == next_episode_num:
            start_ep_idx = i
            found = True
            break

    if not found:
        print_warning(f"Could not automatically find Episode {next_episode_num}. Please select:")
        ep_options = [e.title for e in episodes] + ["← Back"]
        start_ep_idx = select_from_list(ep_options, "📺 Select Episode:")
        if start_ep_idx == len(episodes):
            return None
    else:
        print_success(f"Found Episode {next_episode_num}: {episodes[start_ep_idx].title}")

    return start_ep_idx
