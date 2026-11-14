import re
import urllib.parse

from curl_cffi import requests

from ..cli_utils import (
    get_user_input,
    pause,
    print_header,
    print_info,
    print_success,
    print_warning,
    select_from_list,
)
from ..languages import get_language_label
from ..player_manager import play_video
from ..scraping import metadata
from ..scraping import player as player_scraper
from ..scraping.goldenms import goldenms_extractor
from ..scraping.subtitles import subtitle_extractor
from ..tracker import tracker
from .subtitle_prompt import describe_subtitle


def search_cinemeta(title: str, is_movie: bool):
    """Search TMDB/IMDB using Cinemeta API."""
    media_type = "movie" if is_movie else "series"
    url = f"https://v3-cinemeta.strem.io/catalog/{media_type}/top/search={urllib.parse.quote(title)}.json"

    try:
        r = requests.get(url, timeout=10, impersonate="chrome").json()
        metas = r.get("metas", [])
        return metas
    except Exception as e:
        print_warning(f"Error fetching Cinemeta search data: {e}")
        return []


def _normalize_candidate(candidate: dict) -> dict:
    """One display/search shape for TMDB and Cinemeta candidates."""
    name = candidate.get("name") or candidate.get("title") or "Unknown Title"
    year = candidate.get("year")
    if isinstance(year, str):
        year = int(year[:4]) if year[:4].isdigit() else None
    imdb_id = candidate.get("imdb_id") or candidate.get("id") or ""
    return {
        "name": name,
        "title": name,
        "year": year,
        "releaseInfo": str(year) if year else "Unknown",
        "imdb_id": imdb_id,
        "tmdb_id": candidate.get("tmdb_id"),
        "is_movie": candidate.get("is_movie"),
        "poster": candidate.get("poster"),
    }


def search_titles(title: str, is_movie: bool, year: int | None = None) -> list[dict]:
    """Search through the keyless TMDB proxy, falling back to Cinemeta.

    TMDB knows the exact media type and resolves localized titles, which is
    what Cinemeta alone cannot do. Cinemeta stays the fallback when the proxy
    is down or returns nothing.
    """
    candidates = metadata.search_titles(title, is_movie, year)
    if not candidates:
        candidates = metadata.cinemeta_candidates(title, is_movie, year)
    return [_normalize_candidate(candidate) for candidate in candidates]


def _season_map_from_videos(videos) -> dict[int, list[tuple[int, str]]]:
    """Cinemeta ``videos`` -> ``{season: [(episode, name)]}`` (no specials)."""
    season_map: dict[int, list[tuple[int, str]]] = {}
    for video in videos or []:
        if not isinstance(video, dict):
            continue
        try:
            season = int(video.get("season"))
            episode = int(video.get("episode"))
        except (TypeError, ValueError):
            continue
        if season <= 0 or episode <= 0:
            continue
        name = video.get("name") or f"Episode {episode}"
        season_map.setdefault(season, []).append((episode, name))
    for episodes in season_map.values():
        episodes.sort(key=lambda item: item[0])
    return season_map


def _season_map_from_tmdb(tmdb_id: int) -> dict[int, list[tuple[int, str]]]:
    """TMDB episode lists -> ``{season: [(episode, name)]}`` (no specials)."""
    season_map: dict[int, list[tuple[int, str]]] = {}
    if not tmdb_id:
        return season_map
    for season in metadata.tmdb_seasons(tmdb_id):
        if season <= 0:
            continue
        episodes = metadata.tmdb_season_episodes(tmdb_id, season)
        season_map[season] = [
            (episode["episode"], episode.get("name") or f"Episode {episode['episode']}")
            for episode in episodes
            if episode.get("episode")
        ]
    return season_map


def get_cinemeta_details(imdb_id: str, is_movie: bool):
    """Get full metadata including TMDB ID from Cinemeta."""
    media_type = "movie" if is_movie else "series"
    url = f"https://v3-cinemeta.strem.io/meta/{media_type}/{imdb_id}.json"
    try:
        r = requests.get(url, timeout=10, impersonate="chrome").json()
        return r.get("meta", {})
    except Exception as e:
        print_warning(f"Error fetching Cinemeta details: {e}")
        return {}


def _is_valid(r):
    url = r.get("url", "")
    type_ = r.get("type", "").upper()
    return (
        type_ == "M3U8"
        or type_ == "MPD"
        or type_ in ("VIDEO", "MP4")
        or ".m3u8" in url
        or ".mpd" in url.lower()
        or "master" in url.lower()
        or player_scraper.is_supported(url)
    )


def handle_goldenms():
    """Main entry point for the GoldenMS provider (Movies & Series)."""
    print_header("GoldenMS (Movies & Series)")

    choices = ["Movie", "Series", "← Back"]
    c_idx = select_from_list(choices, "Select Type:")
    if c_idx == 2:
        return

    is_movie = c_idx == 0
    type_str = "Movie" if is_movie else "Series"

    title = get_user_input(f"Enter {type_str} title")
    if not title:
        return

    print_info(f"Searching TMDB for '{title}'...")
    metas = search_titles(title, is_movie)

    if not metas:
        print_warning("No results found.")
        pause()
        return

    # User select result
    display_options = []
    for m in metas:
        year = m.get("year") or "Unknown"
        name = m.get("name") or "Unknown Title"
        display_options.append(f"{name} ({year})")

    display_options.append("← Cancel")
    selection_idx = select_from_list(display_options, "Select Match:")

    if selection_idx == len(metas):
        return

    selected_meta = metas[selection_idx]
    media_title = selected_meta.get("name") or title
    imdb_id = selected_meta.get("imdb_id") or ""

    # Cinemeta still carries the poster and, for series, the episode list.
    print_info("Fetching full metadata...")
    full_meta = get_cinemeta_details(imdb_id, is_movie) if imdb_id else {}

    tmdb_id = selected_meta.get("tmdb_id") or full_meta.get("moviedb_id")
    if not tmdb_id and imdb_id:
        tmdb_id = metadata.find_tmdb_id(imdb_id, is_movie)
    if not tmdb_id:
        print_warning("TMDB ID not found, some sources might degrade.")

    release_year = (
        full_meta.get("year")
        or selected_meta.get("year")
        or metadata.year_from_title(title)
    )

    season = None
    episode = None

    if not is_movie:
        season_map = _season_map_from_videos(full_meta.get("videos"))
        if not season_map and tmdb_id:
            print_info("Fetching episode list from TMDB...")
            season_map = _season_map_from_tmdb(tmdb_id)

        if season_map:
            sorted_seasons = sorted(season_map.keys())

            season_options = [f"Season {s}" for s in sorted_seasons] + ["Manual Input", "← Back"]
            s_idx = select_from_list(season_options, "Select Season:")

            if s_idx == len(sorted_seasons) + 1:
                return
            elif s_idx == len(sorted_seasons):
                season_str = get_user_input("Enter season number", default="1")
                if season_str is None:
                    return
                season = int(season_str) if season_str.isdigit() else 1
                ep_str = get_user_input("Enter episode number", default="1")
                if ep_str is None:
                    return
                episode = int(ep_str) if ep_str.isdigit() else 1
            else:
                season = sorted_seasons[s_idx]

                episodes_list = sorted(season_map[season], key=lambda x: x[0])
                ep_options = [f"E{ep[0]:02d} - {ep[1]}" for ep in episodes_list] + [
                    "Manual Input",
                    "← Cancel",
                ]
                ep_idx = select_from_list(
                    ep_options, f"Select Episode (Season {season}):"
                )

                if ep_idx == len(episodes_list) + 1:
                    return
                elif ep_idx == len(episodes_list):
                    ep_str = get_user_input("Enter episode number", default="1")
                    if ep_str is None:
                        return
                    episode = int(ep_str) if ep_str.isdigit() else 1
                else:
                    episode = episodes_list[ep_idx][0]
        else:
            season_str = get_user_input("Enter season number", default="1")
            if season_str is None:
                return
            season = int(season_str) if season_str.isdigit() else 1

            ep_str = get_user_input("Enter episode number", default="1")
            if ep_str is None:
                return
            episode = int(ep_str) if ep_str.isdigit() else 1

    _flow_goldenms_stream(
        title=media_title,
        tmdb_id=tmdb_id,
        imdb_id=imdb_id,
        year=release_year,
        season=season,
        episode=episode,
        is_movie=is_movie,
        logo_url=full_meta.get("poster") or selected_meta.get("poster"),
    )


def _flow_goldenms_stream(
    title, tmdb_id, imdb_id, year, season, episode, is_movie, logo_url
):
    print_info("Searching for streams (this may take a moment)...")
    results = goldenms_extractor.extract(
        title=title,
        tmdb_id=tmdb_id,
        imdb_id=imdb_id,
        year=year if is_movie else None,
        season=season,
        episode=episode,
    )

    valid_results = [r for r in results if _is_valid(r)]

    if not valid_results:
        print_warning("No supported streams found.")
        pause()
        return

    if len(valid_results) < len(results):
        skipped = len(results) - len(valid_results)
        print_info(f"[dim]Skipped {skipped} unsupported stream(s).[/dim]")

    while True:
        choice_idx = select_from_list(
            [
                f"{r['source']} - {r['quality']} ({r['type']})"
                for r in valid_results
            ]
            + ["← Back"],
            "📺 Select Stream:",
        )

        if choice_idx == len(valid_results):
            return

        selection = valid_results[choice_idx]

        # Subtitles logic
        subtitle_tracks = None
        user_lang = tracker.get_language() or "fr"
        lang_name = get_language_label(user_lang)

        embedded_tracks = selection.get("subtitles") or []
        if embedded_tracks:
            langs_preview = ", ".join(
                sorted({t.get("lang", "?") for t in embedded_tracks})
            )
            use_embedded = select_from_list(
                [
                    f"Yes (load {len(embedded_tracks)} tracks: {langs_preview})",
                    "No (search external subtitles)",
                    "← Back",
                ],
                "The stream has embedded subtitle tracks (language picked in the player):",
            )
            if use_embedded == 0:
                subtitle_tracks = embedded_tracks
            elif use_embedded == 2:
                continue

        if subtitle_tracks is None:
            want_subs = select_from_list(
                ["Yes", "No", "← Back"], f"Search for {lang_name} subtitles?"
            )
            if want_subs == 2:
                continue
            if want_subs == 0:
                current_imdb_id = imdb_id
                if not current_imdb_id:
                    current_imdb_id = get_user_input(
                        "Enter IMDB ID (e.g. tt0388629, leave blank to skip subtitles)"
                    )
                if current_imdb_id:
                    sub_season = season if not is_movie else None
                    sub_ep = episode if not is_movie else None
                    release = selection.get("release") or (
                        f"{title} ({year})" if year else title
                    )

                    print_info(f"Searching for {lang_name} subtitles...")
                    subs = subtitle_extractor.search(
                        imdb_id=current_imdb_id,
                        season=sub_season,
                        episode=sub_ep,
                        lang_filter=user_lang,
                        release=release,
                    )

                    if subs:
                        sub_opts = [describe_subtitle(s) for s in subs] + [
                            "← Back",
                            "Skip Subtitles",
                        ]
                        sub_choice = select_from_list(sub_opts, "Select Subtitle:")
                        if sub_choice < len(subs):
                            subtitle_tracks = [subs[sub_choice]]
                            print_info(f"Selected subtitle: {subs[sub_choice]['url']}")
                        elif sub_choice == len(subs):
                            continue
                    else:
                        print_warning(f"No {lang_name} subtitles found.")
                        pause()

        final_url = selection["url"]
        type_ = selection["type"].upper()

        is_direct = (
            ".m3u8" in final_url.lower()
            or ".mpd" in final_url.lower()
            or ".mp4" in final_url.lower()
            or type_ in ("MPD", "MP4", "M3U8")
        )

        # Player Support
        if player_scraper.is_supported(final_url) and not is_direct:
            print_info(f"Resolving player link: [cyan]{final_url}[/cyan]")
            try:
                resolved_url = player_scraper.get_hls_link(final_url)
                if resolved_url:
                    final_url = resolved_url
                    print_info(f"Resolved to: [cyan]{final_url}[/cyan]")
                else:
                    print_warning("Failed to extract raw stream from player.")
                    if select_from_list(["Try to play anyway", "Cancel"], "Action:") == 1:
                        continue
            except Exception as e:
                print_warning(f"Error resolving player: {e}")

        # Display Title
        if is_movie:
            display_title = f"{title} (Movie)"
        else:
            display_title = f"{title} - S{season:02d}E{episode:02d}"

        print_info(f"Starting playback: [cyan]{display_title}[/cyan]")

        headers = dict(selection.get("headers") or {})
        headers.setdefault(
            "User-Agent",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        )
        # The extractor ships VidLink's Referer/Origin and, for DASH
        # manifests, the CloudFront signed cookie (playlistHeaders): keep
        # them, they authorize every manifest/segment fetch.

        success = play_video(
            final_url,
            headers=headers,
            title=display_title,
            subtitle_url=None,
            subtitles=subtitle_tracks,
            is_direct=is_direct,
            is_mp4=selection["type"].upper() == "MP4",
        )

        if success:
            # History
            tracker.save_progress(
                provider="GoldenMS",
                series_title=title,
                season_title="Movie" if is_movie else f"Season {season}",
                episode_title="Movie" if is_movie else f"Episode {episode}",
                series_url=f"tmdb:{tmdb_id}|imdb:{imdb_id}",
                season_url="",
                episode_url="",  # re-search on resume
                logo_url=logo_url,
            )
            print_success("Local progress saved.")

            if not is_movie:
                if (
                    select_from_list(
                        ["Yes", "No"], f"Play Next Episode (Episode {episode + 1})?"
                    )
                    == 0
                ):
                    _flow_goldenms_stream(
                        title=title,
                        tmdb_id=tmdb_id,
                        imdb_id=imdb_id,
                        year=year,
                        season=season,
                        episode=episode + 1,
                        is_movie=False,
                        logo_url=logo_url,
                    )
            return
        # Playback failed: let the user pick another source (many provider
        # links are dead or expired), or go back.
        change_source = select_from_list(
            ["Try another source", "← Back"],
            "Playback failed or was cancelled. What would you like to do?",
        )
        if change_source == 1:
            pause()
            return


def resume_goldenms(data):
    """Resume GoldenMS playback from history."""
    title = data["series_title"]
    is_movie = data.get("season_title") == "Movie"

    season_str = data.get("season_title", "").replace("Season ", "")
    season = int(season_str) if season_str.isdigit() else 1

    episode_str = data.get("episode_title", "").replace("Episode ", "")
    episode = int(episode_str) if episode_str.isdigit() else 1

    tmdb_id = None
    imdb_id = None
    series_url = data.get("series_url", "")
    if "tmdb:" in series_url or re.match(r"^\d+", series_url):
        match = re.search(r"(?:tmdb:)?(\d+)", series_url)
        if match:
            tmdb_id = int(match.group(1))
    if "imdb:" in series_url:
        match = re.search(r"(?:imdb:)?(tt\d+)", series_url)
        if match:
            imdb_id = match.group(1)

    if is_movie:
        display_title = f"{title} (Movie)"
        options = ["▶ Watch again", "← Cancel"]
    else:
        display_title = f"{title} - S{season:02d}E{episode:02d}"
        options = [
            f"▶ Continue (Episode {episode + 1})",
            f"🔁 Watch again (Episode {episode})",
            "← Cancel",
        ]

    print_info(f"Found progress: [cyan]{display_title}[/cyan]")
    choice_idx = select_from_list(options, "What would you like to do?")

    if choice_idx == len(options) - 1:
        return

    if not is_movie and choice_idx == 0:
        episode += 1

    _flow_goldenms_stream(
        title=title,
        tmdb_id=tmdb_id,
        imdb_id=imdb_id,
        year=None,  # Not critical for resume if we have tmdb_id
        season=season,
        episode=episode,
        is_movie=is_movie,
        logo_url=data.get("logo_url"),
    )
