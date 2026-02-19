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


def search_imdb_id(title: str):
    import urllib.parse

    try:
        url_series = f"https://v3-cinemeta.strem.io/catalog/series/top/search={urllib.parse.quote(title)}.json"
        r_series = requests.get(url_series, timeout=5).json()
        metas = r_series.get("metas", [])

        url_movie = f"https://v3-cinemeta.strem.io/catalog/movie/top/search={urllib.parse.quote(title)}.json"
        r_movie = requests.get(url_movie, timeout=5).json()
        metas.extend(r_movie.get("metas", []))

        if metas:
            choices = []
            valid_metas = []
            for m in metas[:7]:  # Top 7 results
                name = m.get("name")
                year = m.get("year", "Unknown")
                m_type = m.get("type", "series")
                imdb = m.get("imdb_id")
                if imdb:
                    choices.append(f"{name} ({year}) - {m_type}")
                    valid_metas.append(m)

            if valid_metas:
                choices.append("Enter manually")
                choices.append("Skip subtitles")

                idx = select_from_list(choices, f"Select IMDB match for '{title}':")
                if idx < len(valid_metas):
                    selected = valid_metas[idx]
                    return selected["imdb_id"], selected["type"] == "movie"
                elif idx == len(valid_metas):
                    manual = get_user_input("Enter IMDB ID manually (e.g. tt0388629)")
                    return manual, False
                else:
                    return None, False
    except Exception as e:
        print_warning(f"Auto IMDB search failed: {e}")

    manual = get_user_input(
        "Enter IMDB ID manually (e.g. tt0388629, leave blank to skip)"
    )
    return manual, False


def handle_goldenanime():
    """Handle GoldenAnime provider flow."""
    print_header("✨ GoldenAnime (VO)")

    query = get_user_input("Search query (Title or AniList ID) (or 'exit' to back)")
    if not query or query.lower() == "exit":
        return

    anilist_id = None
    title = None
    max_episodes = None

    if query.isdigit():
        anilist_id = int(query)
        print_info(f"Fetching AniList data for ID: [cyan]{anilist_id}[/cyan]")
        from ..anilist import anilist_client

        media = anilist_client.get_media_with_relations(anilist_id)
        if media:
            title = media.get("title", {}).get("english") or media.get("title", {}).get(
                "romaji"
            )
            max_episodes = media.get("episodes")
    else:
        title = query
        print_info(f"Searching AniList by Title: [cyan]{title}[/cyan]")
        from ..anilist import anilist_client

        results = anilist_client.search_media(title)
        if results:
            media_options = [
                f"{m['title']['english'] or m['title']['romaji']} ({m.get('seasonYear', '?')}) - {m.get('episodes', '?')} eps"
                for m in results
            ] + ["Manual input (Skip AniList)"]
            m_idx = select_from_list(media_options, "Select AniList Match:")
            if m_idx < len(results):
                match = results[m_idx]
                anilist_id = match["id"]
                title = match["title"]["english"] or match["title"]["romaji"]
                max_episodes = match.get("episodes")

    # Episode Selection
    episode = 1
    if max_episodes:
        ep_options = [f"Episode {i}" for i in range(1, max_episodes + 1)] + [
            "Manual input"
        ]
        ep_idx = select_from_list(ep_options, "📺 Select Episode:")
        if ep_idx < max_episodes:
            episode = ep_idx + 1
        else:
            ep_input = get_user_input("Episode number")
            episode = int(ep_input) if ep_input and ep_input.isdigit() else 1
    else:
        ep_input = get_user_input("Episode number (default 1)")
        episode = int(ep_input) if ep_input and ep_input.isdigit() else 1

    # To save time, if we want subs we can auto-search now, but let's do it after we get stream results
    # so we don't block the stream search. Wait, doing it now parallelizes the thought, but it's fine
    # doing it sequentially.

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
    want_subs = select_from_list(["Yes", "No"], "Search for French subtitles?")
    if want_subs == 0:
        # Try to resolve title if missing
        search_title = title
        if not search_title and anilist_id:
            from ..anilist import anilist_client

            media = anilist_client.get_media_with_relations(anilist_id)
            if media:
                search_title = media.get("title", {}).get("english") or media.get(
                    "title", {}
                ).get("romaji")

        imdb_id = None
        is_movie = False
        if search_title:
            imdb_id, is_movie = search_imdb_id(search_title)
        else:
            imdb_id = get_user_input(
                "Enter IMDB ID manually (e.g. tt0388629, leave blank to skip)"
            )

        if imdb_id:
            season = None
            if not is_movie:
                season_options = [f"Season {i}" for i in range(1, 11)] + [
                    "Manual Input"
                ]
                s_idx = select_from_list(
                    season_options, "Select Season (for subtitles mapping):"
                )
                if s_idx < 10:
                    season = s_idx + 1
                else:
                    season_input = get_user_input("Season number (default 1)")
                    season = (
                        int(season_input)
                        if season_input and season_input.isdigit()
                        else 1
                    )

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
