from ..scraping.goldenanime import goldenanime
from ..scraping.subtitles import subtitle_extractor
from ..cli_utils import (
    select_from_list,
    print_header,
    print_info,
    print_warning,
    print_success,
    get_user_input,
    pause,
    console,
)
from ..player_manager import play_video
from ..tracker import tracker
from ..languages import get_language_label
from ..anilist import anilist_client
from ..scraping import player as player_scraper

from curl_cffi import requests
import re


def search_imdb_id(title: str):
    import urllib.parse

    try:
        url_series = f"https://v3-cinemeta.strem.io/catalog/series/top/search={urllib.parse.quote(title)}.json"
        r_series = requests.get(url_series, timeout=5, impersonate="chrome").json()
        metas = r_series.get("metas", [])

        url_movie = f"https://v3-cinemeta.strem.io/catalog/movie/top/search={urllib.parse.quote(title)}.json"
        r_movie = requests.get(url_movie, timeout=5, impersonate="chrome").json()
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
    cover_url = None

    if query.isdigit():
        anilist_id = int(query)
        print_info(f"Fetching AniList data for ID: [cyan]{anilist_id}[/cyan]")
        media = anilist_client.get_media_with_relations(anilist_id)
        if media:
            title = media.get("title", {}).get("english") or media.get("title", {}).get(
                "romaji"
            )
            max_episodes = media.get("episodes")
            cover_url = media.get("coverImage", {}).get("large") or media.get(
                "coverImage", {}
            ).get("medium")
    else:
        title = query
        print_info(f"Searching AniList by Title: [cyan]{title}[/cyan]")
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
                cover_url = match.get("coverImage", {}).get("medium")

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

    # Proceed to episode loop (handles next episode proposal)
    handle_goldenanime_episode(
        title=title, anilist_id=anilist_id, start_episode=episode, cover_url=cover_url
    )


def _flow_goldenanime_stream(
    title: str, anilist_id: int, episode: int, cover_url: str = None
):
    """Common logic for searching streams, subtitles, and playing."""
    print_info("Searching for streams...")
    results = goldenanime.extract_vo(
        title=title, anilist_id=anilist_id, episode=episode
    )

    if not results:
        print_warning("No results found.")
        pause()
        return

    # Filter: only keep direct streams (m3u8 / mp4) or supported embedded players
    def _is_valid(r):
        url = r.get("url", "")
        rtype = (r.get("type") or "").lower()
        return (
            rtype in ("m3u8", "hls", "mp4")
            or ".m3u8" in url
            or ".m3u" in url
            or "master" in url.lower()
            or player_scraper.is_supported(url)
        )

    valid_results = [r for r in results if _is_valid(r)]

    if not valid_results:
        print_warning(
            "No supported streams found (no direct M3U8 or recognised players)."
        )
        pause()
        return

    if len(valid_results) < len(results):
        skipped = len(results) - len(valid_results)
        print_info(f"[dim]Skipped {skipped} unsupported stream(s).[/dim]")

    choice_idx = select_from_list(
        [f"{r['source']} - {r['quality']} ({r['type']})" for r in valid_results]
        + ["← Back"],
        "📺 Select Stream:",
    )

    if choice_idx == len(valid_results):  # Back
        return

    selection = valid_results[choice_idx]

    # Subtitles logic
    subtitle_tracks = None
    user_lang = tracker.get_language() or "fr"
    lang_name = get_language_label(user_lang)

    embedded_tracks = selection.get("subtitles") or []
    if embedded_tracks:
        langs_preview = ", ".join(sorted({t.get("lang", "?") for t in embedded_tracks}))
        use_embedded = select_from_list(
            [
                f"Yes (load {len(embedded_tracks)} tracks: {langs_preview})",
                "No (search external subtitles)",
            ],
            "The stream has embedded subtitle tracks (language picked in the player):",
        )
        if use_embedded == 0:
            subtitle_tracks = embedded_tracks

    if subtitle_tracks is None:
        # Try to resolve title if missing
        search_title = title
        if not search_title and anilist_id:
            media = anilist_client.get_media_with_relations(anilist_id)
            if media:
                search_title = media.get("title", {}).get("english") or media.get(
                    "title", {}
                ).get("romaji")

        want_subs = select_from_list(
            ["Yes", "No"], f"Search for {lang_name} subtitles?"
        )
        if want_subs == 0:
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
                    # Detect season from title for smart default
                    default_season_idx = 0
                    if search_title:
                        match = re.search(r"Season\s+(\d+)", search_title, re.IGNORECASE)
                        if match:
                            detected_season = int(match.group(1))
                            # Range 1-10 mapped to 0-9 index
                            if 1 <= detected_season <= 10:
                                default_season_idx = detected_season - 1

                    season_options = [f"Season {i}" for i in range(1, 11)] + [
                        "Manual Input"
                    ]
                    s_idx = select_from_list(
                        season_options,
                        "Select Season (for subtitles mapping):",
                        default_index=default_season_idx,
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

                print_info(f"Searching for {lang_name} subtitles...")
                anidb_id = None
                if anilist_id:
                    mappings = goldenanime.get_mappings(anilist_id)
                    anidb_id = mappings.get("anidbId")
                subs = subtitle_extractor.search(
                    imdb_id=imdb_id,
                    season=season,
                    episode=episode,
                    lang_filter=user_lang,
                    anidb_id=anidb_id,
                )

                if subs:
                    # Show a shortened list to make it faster
                    sub_choices = [
                        f"{s['source']} - {s.get('lang', lang_name)}" for s in subs[:6]
                    ] + ["None"]
                    sub_idx = select_from_list(sub_choices, "📝 Select Subtitle:")
                    if sub_idx < len(sub_choices) - 1:
                        subtitle_tracks = [subs[sub_idx]]
                        print_info(f"Selected subtitle from: {subs[sub_idx]['source']}")
                else:
                    print_warning(f"No {lang_name} subtitles found.")

    print_info(f"Loading stream from [cyan]{selection['source']}[/cyan]...")

    headers = selection.get("headers") or {"Referer": goldenanime.referer + "/"}

    display_title = title if title else f"AniList ID {anilist_id}"

    final_url = selection["url"]

    is_direct = (
        selection["type"].lower() == "m3u8"
        or "m3u8" in final_url
        or selection["type"].lower() == "mp4"
    )

    success = play_video(
        final_url,
        headers=headers,
        title=f"{display_title} - Episode {episode}",
        subtitle_url=None,
        subtitles=subtitle_tracks,
        is_direct=is_direct,
        is_mp4=selection["type"].lower() == "mp4",
    )

    if success:
        # Save local progress with rich metadata
        tracker.save_progress(
            provider="GoldenAnime",
            series_title=display_title,
            season_title="VO",
            episode_title=f"Episode {episode}",
            series_url=f"anilist:{anilist_id}" if anilist_id else "",
            season_url="",
            episode_url="",  # URL expires; re-search on resume
            logo_url=cover_url,
        )
        print_success("Local progress saved.")

        # Sync AniList if authenticated
        if anilist_id:
            token = tracker.get_anilist_token()
            if token:
                anilist_client.set_token(token)
                if anilist_client.update_progress(anilist_id, episode):
                    print_success(f"AniList updated to episode {episode}!")
                else:
                    print_warning("Could not update AniList.")

    else:
        print_warning("Playback failed or was cancelled.")
        pause()
        return False

    return True


def handle_goldenanime_episode(
    title: str, anilist_id: int, start_episode: int, cover_url: str = None
):
    """Loop: play episode, then propose next, or stop."""
    episode = start_episode
    while True:
        success = _flow_goldenanime_stream(
            title=title, anilist_id=anilist_id, episode=episode, cover_url=cover_url
        )
        if success:
            next_ep = episode + 1
            choice = select_from_list(
                [f"▶ Play Episode {next_ep}", "← Back"],
                f"Episode {episode} finished:",
            )
            if choice == 0:
                episode = next_ep
                continue
        break


def resume_goldenanime(data):
    """Resume GoldenAnime playback from history."""
    title = data["series_title"]
    episode_str = data["episode_title"].replace("Episode ", "")
    episode = int(episode_str) if episode_str.isdigit() else 1

    # Recover anilist_id from series_url field (stored as "anilist:12345")
    anilist_id = None
    series_url = data.get("series_url", "")
    if series_url.startswith("anilist:"):
        id_str = series_url.replace("anilist:", "")
        if id_str.isdigit():
            anilist_id = int(id_str)
    elif series_url.isdigit():
        # Fallback for broken history entries where the prefix was stripped
        anilist_id = int(series_url)
    # Legacy fallback: title used to encode the ID
    elif title and title.startswith("AniList ID "):
        id_str = title.replace("AniList ID ", "")
        if id_str.isdigit():
            anilist_id = int(id_str)
            title = None

    display_title = title if title else f"AniList ID {anilist_id}"
    print_info(f"Found progress: [cyan]{display_title}[/cyan] - Episode {episode}")

    options = [
        f"▶ Continue (Episode {episode + 1})",
        f"🔁 Watch again (Episode {episode})",
        "← Cancel",
    ]
    choice = select_from_list(options, "What would you like to do?")

    if choice == 2:  # Cancel
        return
    elif choice == 0:  # Next
        episode += 1

    handle_goldenanime_episode(
        title=title, anilist_id=anilist_id, start_episode=episode
    )
