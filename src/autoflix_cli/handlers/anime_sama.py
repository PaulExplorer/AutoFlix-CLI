from ..scraping import anime_sama, player
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


# On Anime-Sama, "vostfr" is the original version (VO), everything else
# (vf, vf1, vf2, vcn, ...) is a translated/dubbed version.
VO_CODE = "vostfr"


def pick_language_auto(langs):
    """Return a language code to auto-select, or None to ask the user.

    Behavior driven by the Anime-Sama language setting:
      - "vo"    -> auto-select the VO (VOSTFR) when it is available.
      - "other" -> when the choice is exactly VO vs one other version, take
                   the other one; with more options, do nothing and ask.
      - "manual"-> never auto-select, always ask.
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
        print_info(f"Language automatically set to [cyan]{auto_lang.upper()}[/cyan]")
        return auto_lang

    lang_options = langs + ["← Back"]
    lang_idx = select_from_list(lang_options, prompt)
    if lang_idx == len(langs):
        return None
    return langs[lang_idx]


def handle_anime_sama():
    """Handle Anime-Sama provider flow."""
    anime_sama.get_website_url()

    print_header("🎌 Anime-Sama")

    while True:
        query = get_user_input("Search query (or 'exit' to back)")
        if not query or query.lower() == "exit":
            return

        print_info(f"Searching for: [cyan]{query}[/cyan]")
        results = anime_sama.search(query)

        if not results:
            print_warning("No results found.")
            pause()
            continue

        while True:
            # options = [f"{r.title} ({', '.join(r.genres)})" for r in results] + ["← Back"] # Anime-Sama doesn't give genres anymore
            options = [f"{r.title}" for r in results] + ["← Back"]
            choice_idx = select_from_list(options, "📺 Search Results:")

            if choice_idx == len(results):
                break

            selection = results[choice_idx]

            print_info(f"Loading [cyan]{selection.title}[/cyan]...")
            series = anime_sama.get_series(selection.url)

            if not series.seasons:
                print_warning("No seasons found.")
                pause()
                continue

            saved_progress = tracker.get_series_progress("Anime-Sama", series.title)
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
                    resume_anime_sama(saved_progress)
                    return
                if choice == 2:
                    continue

            season_options = [s.title for s in series.seasons] + ["← Back"]
            season_idx = select_from_list(season_options, "📺 Select Season:")
            if season_idx == len(series.seasons):
                continue
            selected_season_access = series.seasons[season_idx]

            print_info(f"Loading [cyan]{selected_season_access.title}[/cyan]...")
            try:
                season = anime_sama.get_season(selected_season_access.url)
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

                success = play_episode_flow(
                    provider_name="Anime-Sama",
                    series_title=series.title,
                    season_title=season.title,
                    episode=selected_episode,
                    series_url=series.url,
                    season_url=selected_season_access.url,
                    logo_url=series.img,
                    headers={"Referer": anime_sama.website_origin},
                    anilist_callback=lambda: _update_anilist_progress(
                        "Anime-Sama", series, season, selected_episode
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


def resume_anime_sama(data):
    """Resume Anime-Sama playback."""
    print_info(f"Resuming [cyan]{data['series_title']}[/cyan]...")

    # We need to reload just the season to find the episode link/player
    # We have season_url saved.
    anime_sama.get_website_url()

    # Re-fetch season
    season_url = data["season_url"]
    if season_url.startswith("/") or not season_url.startswith("http"):
        season_url = anime_sama.website_origin.rstrip("/") + season_url

    print_info(f"Loading Season: {season_url}")
    try:
        season = anime_sama.get_season(season_url)
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

    # Create dummy series object for callback
    class SeriesDummy:
        def __init__(self, t):
            self.title = t

    series_dummy = SeriesDummy(data["series_title"])

    while True:
        selected_episode = episodes[ep_idx]

        success = play_episode_flow(
            provider_name="Anime-Sama",
            series_title=data["series_title"],
            season_title=season.title,
            episode=selected_episode,
            series_url=data["series_url"],
            season_url=data["season_url"],
            logo_url=data.get("logo_url"),
            headers={"Referer": anime_sama.website_origin},
            anilist_callback=lambda: _update_anilist_progress(
                "Anime-Sama", series_dummy, season, selected_episode
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
