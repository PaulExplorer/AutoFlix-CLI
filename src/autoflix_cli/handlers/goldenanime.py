from ..scraping.goldenanime import goldenanime
from ..scraping.subtitles import subtitle_extractor
from ..cli_utils import (
    select_from_list,
    print_header,
    print_info,
    print_warning,
    get_user_input,
    console,
)
from ..player_manager import play_video


import requests


def handle_goldenanime():
    """Handle GoldenAnime provider flow."""
    print_header("✨ GoldenAnime (VO)")

    query = get_user_input("Search query (Title or AniList ID) (or 'exit' to back)")
    if not query or query.lower() == "exit":
        return

    anilist_id = None
    title = None
    if query.isdigit():
        anilist_id = int(query)
        print_info(f"Searching by AniList ID: [cyan]{anilist_id}[/cyan]")
    else:
        title = query
        print_info(f"Searching by Title: [cyan]{title}[/cyan]")

    ep_input = get_user_input("Episode number (default 1)")
    episode = int(ep_input) if ep_input and ep_input.isdigit() else 1

    # Ask for IMDB ID upfront to save manual steps later
    imdb_id = get_user_input(
        "IMDB ID for French subs (e.g., tt0388629, leave blank to skip)"
    )
    season = None
    if imdb_id:
        season_input = get_user_input(
            "Season number (default 1, leave blank for movies)"
        )
        season = int(season_input) if season_input and season_input.isdigit() else 1
        if season_input.strip() == "":
            season = None

    print_info("Searching for streams...")
    results = goldenanime.extract_vo(
        title=title, anilist_id=anilist_id, episode=episode
    )

    if not results:
        print_warning("No results found.")
        return

    choice_idx = select_from_list(
        [f"{r['source']} - {r['quality']} ({r['type']})" for r in results],
        "📺 Search Results:",
    )
    selection = results[choice_idx]

    # Subtitles logic
    subtitle_url = None
    if imdb_id:
        print_info("Searching for subtitles...")
        subs = subtitle_extractor.search(
            imdb_id=imdb_id, season=season, episode=episode, lang_filter="French"
        )

        if subs:
            # Show a shortened list to make it faster
            sub_choices = [
                f"{s['source']} - {s.get('lang', 'Unknown')}" for s in subs[:5]
            ] + ["None"]
            sub_idx = select_from_list(sub_choices, "📝 Select Subtitle:")
            if sub_idx < len(sub_choices) - 1:
                subtitle_url = subs[sub_idx]["url"]
                print_info(f"Selected subtitle from: {subs[sub_idx]['source']}")
        else:
            print_warning("No French subtitles found.")

    print_info(f"Loading stream from [cyan]{selection['source']}[/cyan]...")

    headers = {"User-Agent": goldenanime.user_agent, "Referer": "https://sudatchi.com/"}
    if "Allanime" in selection["source"]:
        headers["Referer"] = "https://allmanga.to/"

    display_title = title if title else f"AniList ID {anilist_id}"

    # Handle specific API URLs that return JSON instead of M3U8 directly
    final_url = selection["url"]
    if "sudatchi.com/api/streams" in final_url:
        try:
            resp = requests.get(final_url, headers=headers).json()
            if isinstance(resp, list) and len(resp) > 0:
                final_url = resp[0].get("url", final_url)
        except Exception:
            pass

    is_direct = True  # Assume extract_vo returns direct URLs or handled APIs

    play_video(
        final_url,
        headers=headers,
        title=f"{display_title} - Episode {episode}",
        subtitle_url=subtitle_url,
        is_direct=is_direct,
    )
