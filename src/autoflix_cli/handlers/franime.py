from ..scraping import franime
from ..scraping.utils import NoEpisodesFoundError
from ..cli_utils import (
    select_from_list,
    print_header,
    print_info,
    print_warning,
    print_success,
    print_error,
    get_user_input,
    console,
    pause,
)
from ..player_manager import play_video
from ..tracker import tracker
from .playback import play_episode_flow
from .anilist_update import _update_anilist_progress


# On FRAnime the catalogue exposes exactly two languages: "vo" (original
# with subtitles) and "vf" (French dub). The season episodes dict keys them
# in uppercase.
VO_CODE = "VO"


def pick_language_auto(langs):
    """Return a language key to auto-select, or None to ask the user.

    Reuses the Anime-Sama language setting ("vo" / "other" / "manual").
    """
    pref = tracker.get_sama_lang_pref()

    if pref == "vo":
        return VO_CODE if VO_CODE in langs else None

    if pref == "other":
        if len(langs) == 2 and VO_CODE in langs:
            return next(code for code in langs if code != VO_CODE)
        return None

    return None


def _select_language(langs, prompt="🌍 Select Language:"):
    """Pick the language using the user's preference, else prompt for it.

    Returns None when the user cancels the manual prompt.
    """
    # Without a real choice to make, there is nothing to prefer.
    if len(langs) == 1:
        return langs[0]

    auto_lang = pick_language_auto(langs)
    if auto_lang:
        print_info(f"Language automatically set to [cyan]{auto_lang}[/cyan]")
        return auto_lang

    lang_options = langs + ["← Back"]
    lang_idx = select_from_list(lang_options, prompt)
    if lang_idx == len(langs):
        return None
    return langs[lang_idx]


def _resolve_episode_players(series_id, season_index, selected_episode, lang):
    """Fill ``selected_episode.players`` with resolved embed URLs.

    Each provider needs one FRAnime resolver call + one offline decryption
    of its watch2 URL, so resolution is deferred until an episode is
    actually selected. Results are cached on the episode object so going
    back and forth in the menus does not re-resolve.
    """
    if selected_episode.players:
        return True

    print_info(f"Resolving sources for [cyan]{selected_episode.title}[/cyan]...")
    selected_episode.players = franime.resolve_players(
        series_id, season_index, selected_episode, lang
    )

    if selected_episode.players:
        print_success(f"{len(selected_episode.players)} source(s) resolved.")
        return True

    print_error("No source could be resolved for this episode.")
    pause()
    return False


def handle_franime():
    """Handle FRAnime provider flow."""
    franime.get_website_url()

    print_header("🎴 FRAnime")

    while True:
        query = get_user_input("Search query (or 'exit' to back)")
        if not query or query.lower() == "exit":
            return

        print_info(f"Searching for: [cyan]{query}[/cyan]")
        try:
            results = franime.search(query)
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
            series = franime.get_series(selection)
        except Exception as e:
            print_error(f"Could not load the anime: {e}")
            pause()
            continue

        if not series.seasons:
            print_warning("No seasons found.")
            pause()
            continue

        saved_progress = tracker.get_series_progress("FRAnime", series.title)
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
                resume_franime(saved_progress)
                return
            if choice == 2:
                continue

        season_options = [s.title for s in series.seasons] + ["← Back"]
        season_idx = select_from_list(season_options, "📺 Select Season:")
        if season_idx == len(series.seasons):
            continue
        selected_season_access = series.seasons[season_idx]

        # The season URL is "https://franime.fr/anime/<id>/<season_index>",
        # the index is what the FRAnime resolver endpoints expect.
        season_index = int(selected_season_access.url.rstrip("/").rsplit("/", 1)[1])

        print_info(f"Loading [cyan]{selected_season_access.title}[/cyan]...")
        try:
            season = franime.get_season(selected_season_access.url)
        except NoEpisodesFoundError:
            print_error(
                "No links found for this content: it is probably not released yet."
            )
            pause()
            continue
        except Exception as e:
            print_error(f"Could not load season: {e}")
            pause()
            continue

        langs = list(season.episodes.keys())
        if not langs:
            print_warning("No episodes found.")
            pause()
            continue

        selected_lang = _select_language(langs)
        if selected_lang is None:
            continue
        episodes = season.episodes[selected_lang]

        ep_options = [e.title for e in episodes] + ["← Back"]
        ep_idx = select_from_list(ep_options, "📺 Select Episode:")
        if ep_idx == len(episodes):
            continue

        while True:
            selected_episode = episodes[ep_idx]

            if not _resolve_episode_players(
                series.url, season_index, selected_episode, selected_lang
            ):
                break

            success = play_episode_flow(
                provider_name="FRAnime",
                series_title=series.title,
                season_title=season.title,
                episode=selected_episode,
                series_url=series.url,
                season_url=selected_season_access.url,
                logo_url=series.img,
                headers={"Referer": franime.website_origin + "/"},
                anilist_callback=lambda: _update_anilist_progress(
                    "FRAnime", series, season, selected_episode
                ),
            )

            if success:
                if ep_idx + 1 < len(episodes):
                    next_ep = episodes[ep_idx + 1]
                    choice = select_from_list(
                        ["Yes", "No"], f"Play next episode: {next_ep.title}?"
                    )
                    if choice == 0:
                        ep_idx += 1
                        continue
                break
            else:
                break


def resume_franime(data):
    """Resume FRAnime playback."""
    print_info(f"Resuming [cyan]{data['series_title']}[/cyan]...")

    franime.get_website_url()

    # Re-fetch just the season: the season URL encodes the anime id and the
    # season index, which is everything the FRAnime API needs.
    season_url = data["season_url"]
    match = franime.season_url_re.search(season_url or "")
    if not match:
        print_error("Could not find the saved season.")
        pause()
        return
    anime_id, season_index = match.group(1), int(match.group(2))

    print_info(f"Loading Season: {season_url}")
    try:
        season = franime.get_season(season_url)
    except NoEpisodesFoundError:
        print_error(
            "No links found for this content: it is probably not released yet."
        )
        return
    except Exception as e:
        print_error(f"Could not load season: {e}")
        return

    langs = list(season.episodes.keys())
    if not langs:
        return

    selected_lang = _select_language(langs)
    if selected_lang is None:
        return
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
            pause()
            return

    # Start loop
    ep_idx = start_ep_idx

    # Create dummy series object for anilist callback
    class SeriesDummy:
        def __init__(self, t):
            self.title = t

    series_dummy = SeriesDummy(data["series_title"])

    while True:
        selected_episode = episodes[ep_idx]

        if not _resolve_episode_players(
            anime_id, season_index, selected_episode, selected_lang
        ):
            return

        success = play_episode_flow(
            provider_name="FRAnime",
            series_title=data["series_title"],
            season_title=season.title,
            episode=selected_episode,
            series_url=anime_id,
            season_url=season_url,
            logo_url=data.get("logo_url"),
            headers={"Referer": franime.website_origin + "/"},
            anilist_callback=lambda: _update_anilist_progress(
                "FRAnime", series_dummy, season, selected_episode
            ),
        )

        if success:
            if ep_idx + 1 < len(episodes):
                next_ep = episodes[ep_idx + 1]
                choice = select_from_list(
                    ["Yes", "No"], f"Play next episode: {next_ep.title}?"
                )
                if choice == 0:
                    ep_idx += 1
                    continue
            break
        else:
            return  # Back
