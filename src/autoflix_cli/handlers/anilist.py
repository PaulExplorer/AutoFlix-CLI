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
)
from . import anime_sama as anime_sama_handler
from ..scraping import anime_sama as anime_sama_scraper
from . import goldenanime
from . import arkanime as arkanime_handler
from ..scraping import arkanime as arkanime_scraper
from .playback import play_episode_flow
from ..player_manager import play_video
from ..scraping import player


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

        # Calculate latest released episode & episodes behind
        next_airing = e["media"].get("nextAiringEpisode")
        latest_released = None
        if next_airing and isinstance(next_airing, dict) and next_airing.get("episode"):
            latest_released = max(0, next_airing["episode"] - 1)
        elif isinstance(e["media"].get("episodes"), int):
            latest_released = e["media"]["episodes"]

        if latest_released is not None:
            behind = max(0, latest_released - progress)
            behind_str = f"{behind} ep behind" if behind > 0 else "Up to date"
        else:
            behind_str = None

        if isinstance(total, int) and progress >= total:
            status_info = f"Finished {progress}/{total}"
        else:
            status_info = f"Ep {progress+1}/{total}"

        if behind_str:
            status = f"{status_info} - {behind_str}"
        else:
            status = status_info

        display_options.append(f"{title} ({status})")

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
    progress = selected_entry["progress"] or 0
    total = selected_entry["media"]["episodes"] or "?"
    next_episode_num = progress + 1

    if isinstance(total, int) and progress >= total:
        print_info(
            f"Target: [cyan]{media_title}[/cyan] - [yellow]Completed ({progress}/{total})[/yellow]"
        )
        # Reset to last episode for easier replay or just stay at progress
        next_episode_num = progress
    else:
        print_info(f"Target: [cyan]{media_title}[/cyan] - Episode {next_episode_num}")

    # --- Provider Selection ---
    providers = ["Anime-Sama (VF/VOSTFR)", "GoldenAnime (VO)", "⛩️ ArkAnime (Anime & Animations)", "← Back"]
    p_choice = select_from_list(providers, "Select Provider:")

    if p_choice == 3:  # Back
        return

    # Extract cover URL for both providers
    cover_url = selected_entry["media"].get("coverImage", {}).get(
        "large"
    ) or selected_entry["media"].get("coverImage", {}).get("medium")

    if p_choice == 1:  # GoldenAnime
        goldenanime.handle_goldenanime_episode(
            title=media_title,
            anilist_id=media_id,
            start_episode=next_episode_num,
            cover_url=cover_url,
        )
        return

    romaji_title = selected_entry["media"]["title"]["romaji"]

    if p_choice == 2:  # ArkAnime
        series = _search_and_select_series(arkanime_scraper, media_title, romaji_title)
        if not series or not series.seasons:
            if series and not series.seasons:
                print_warning("No seasons found.")
            return

        season = _auto_select_season(series.seasons, media_title, romaji_title)
        tracker.set_anilist_mapping("ArkAnime", series.title, media_id, season.title)

        episodes = season.episodes
        if not episodes:
            print_warning("No episodes found.")
            return

        start_ep_idx = _auto_select_episode(episodes, next_episode_num)
        
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
                    series_dummy, season, selected_episode
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
        
        print_info(f"Loading [cyan]{selected_season_access.title}[/cyan]...")
        season = anime_sama_scraper.get_season(selected_season_access.url)
        tracker.set_anilist_mapping("Anime-Sama", series.title, media_id, season.title)

        langs = list(season.episodes.keys())
        if not langs:
            print_warning("No episodes found.")
            return
            
        lang_idx = select_from_list(langs, "🌍 Select Language:")
        episodes = season.episodes[langs[lang_idx]]

        start_ep_idx = _auto_select_episode(episodes, next_episode_num)
        
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
                    series_dummy, season, selected_episode
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
        [s.title for s in series_seasons],
        "📺 Select Season:",
        default_index=default_season_idx,
    )

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
        start_ep_idx = select_from_list([e.title for e in episodes], "📺 Select Episode:")
    else:
        print_success(f"Found Episode {next_episode_num}: {episodes[start_ep_idx].title}")

    return start_ep_idx
