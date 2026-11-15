import time
from typing import NamedTuple

from ..anilist import anilist_client
from ..cli_utils import (
    get_user_input,
    pause,
    print_header,
    print_info,
    print_success,
    print_warning,
    select_from_list,
    supports_live_refresh,
)
from ..languages import get_language_label
from ..player_manager import play_video
from ..scraping import player as player_scraper
from ..scraping.goldenanime import goldenanime, probe_direct_stream
from ..scraping.megaplay import megaplay_extractor
from ..scraping.subtitles import subtitle_extractor
from ..tracker import tracker
from .subtitle_prompt import describe_subtitle, resolve_imdb_id

# Seconds to wait for a first stream before showing the menu anyway. Below
# that the list is often empty on a cold title, above it the user stares at
# a blank screen while the fastest providers have already answered.
FIRST_STREAM_WAIT = 10


def _wait_for_remaining(search, timeout: float = 30.0, report_every: float = 8.0):
    """Wait for the background search, reporting the sources as they land.

    Sources keep arriving on their own: this only blocks so the user can see
    the final list without playing first. Bounded so a slow instance cannot
    trap the user in a silent wait.
    """
    print_info(
        "Still looking for a first source..."
        if not search.snapshot()
        else "Waiting for the remaining sources..."
    )
    deadline = time.monotonic() + timeout
    count = len(search.snapshot())
    last_report = time.monotonic()
    while not search.is_done() and time.monotonic() < deadline:
        search.wait(1)
        found = len(search.snapshot())
        now = time.monotonic()
        if found != count or now - last_report >= report_every:
            count = found
            last_report = now
            print_info(
                f"{found} source(s) so far, {search.pending()} still loading"
            )
    found = len(search.snapshot())
    if search.is_done():
        print_info(f"Search finished: {found} source(s).")
    else:
        print_info(
            f"Still searching: {found} source(s), {search.pending()} still loading."
        )


def _mapping_ids(anilist_id: int | None) -> dict:
    """AniList cross-platform ids (imdbId/anidbId/format/defaultTvdbSeason)."""
    if not anilist_id:
        return {}
    try:
        return goldenanime.get_mappings(anilist_id) or {}
    except Exception:  # noqa: BLE001 - mapping API is best-effort
        return {}


def _mapping_season(mappings: dict) -> int:
    for key in ("defaultTvdbSeason", "tmdbSeason"):
        value = mappings.get(key)
        try:
            season = int(value)
        except (TypeError, ValueError):
            continue
        if season > 0:
            return season
    return 1


def _episode_offset(mappings: dict) -> int:
    """Episodes to add to an AniList number to match TVDB/OpenSubtitles.

    OpenSubtitles names its files after the TVDB season, which does not always
    restart at 1 for a new AniList entry: a split cour is a separate AniList
    entry but one continuous TVDB season. ``episodeOffset`` is authoritative
    when the mapping provides it; otherwise the offset is rebuilt from the
    franchise's prequels that share the same TVDB season.
    """
    if not mappings:
        return 0
    raw = mappings.get("episodeOffset")
    if raw is not None and str(raw).strip() != "":
        try:
            return int(raw)
        except (TypeError, ValueError):
            pass
    return _prequel_offset(mappings)


def _prequel_offset(mappings: dict) -> int:
    """Sum the episodes of the prequels that share this TVDB season."""
    season = _mapping_season(mappings)
    tvdb_id = mappings.get("thetvdbId")
    if not tvdb_id:
        return 0

    total = 0
    seen: set[int] = set()
    for entry in mappings.get("franchise") or []:
        if not isinstance(entry, dict) or entry.get("relation") != "PREQUEL":
            continue
        if (entry.get("format") or "").upper() not in ("TV", "ONA"):
            continue
        anilist_id = entry.get("anilistId")
        if not anilist_id or anilist_id in seen:
            continue
        seen.add(anilist_id)

        prequel = _mapping_ids(anilist_id)
        if not prequel or prequel.get("thetvdbId") != tvdb_id:
            continue
        if _mapping_season(prequel) != season:
            continue
        try:
            total += int(prequel.get("episodes") or 0)
        except (TypeError, ValueError):
            continue
    return total


def _subtitle_episode(
    episode: int, season: int | None, default_season: int, mappings: dict
) -> int:
    """TVDB episode number to query, offsetting only the mapped season.

    A season the user picked by hand has no known offset, so it is used as-is.
    """
    if season != default_season:
        return episode
    return episode + _episode_offset(mappings)


def _ask_subtitle_season(default: int) -> int | None:
    """Ask for a season without pretending there are always ten of them."""
    options = [f"Season {default}", "Other season…", "← Back"]
    index = select_from_list(options, "Select season for the subtitle lookup:")
    if index == 0:
        return default
    if index == 1:
        value = get_user_input(f"Season number (default {default})")
        return int(value) if value and value.isdigit() else default
    return None



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
            ] + ["Manual input (Skip AniList)", "← Back"]
            m_idx = select_from_list(media_options, "Select AniList Match:")
            if m_idx < len(results):
                match = results[m_idx]
                anilist_id = match["id"]
                title = match["title"]["english"] or match["title"]["romaji"]
                max_episodes = match.get("episodes")
                cover_url = match.get("coverImage", {}).get("medium")
            elif m_idx == len(results) + 1:
                return

    # Episode Selection
    episode = 1
    if max_episodes:
        ep_options = [f"Episode {i}" for i in range(1, max_episodes + 1)] + [
            "Manual input",
            "← Back",
        ]
        ep_idx = select_from_list(ep_options, "📺 Select Episode:")
        if ep_idx < max_episodes:
            episode = ep_idx + 1
        elif ep_idx == max_episodes:
            ep_input = get_user_input("Episode number")
            episode = int(ep_input) if ep_input and ep_input.isdigit() else 1
        else:
            return
    else:
        ep_input = get_user_input("Episode number (default 1)")
        episode = int(ep_input) if ep_input and ep_input.isdigit() else 1

    # Proceed to episode loop (handles next episode proposal)
    handle_goldenanime_episode(
        title=title, anilist_id=anilist_id, start_episode=episode, cover_url=cover_url
    )


def _merge_streams(*groups):
    """Concatenate stream lists, dropping duplicate URLs (first one wins)."""
    merged = []
    seen = set()
    for group in groups:
        for entry in group or []:
            url = entry.get("url")
            if not url or url in seen:
                continue
            seen.add(url)
            merged.append(entry)
    return merged


def _is_direct(entry) -> bool:
    """True for a link a player opens directly (as opposed to an embed page)."""
    return (entry.get("type") or "").lower() in ("m3u8", "hls", "mpd", "mp4")


def _probe_failed(entry) -> bool:
    """True once the background check reported this link as unreachable."""
    probe = entry.get("probe") or {}
    return probe.get("ok") is False


def _probe_reason(error) -> str:
    """Condense a probe error into a few characters for the menu."""
    text = str(error or "unreachable").strip()
    lowered = text.lower()
    if text.startswith("HTTP "):
        text = text[5:]
    elif "timed out" in lowered or "timeout" in lowered:
        text = "timeout"
    elif text == "not a playlist":
        text = "no playlist"
    return text[:16]


def _probe_marker(entry) -> str:
    """Verdict suffix shown after a source (" ✓", " ✗ 403").

    Rows are never reordered or hidden: the menu tells the user what the
    background check saw, and picking a flagged link still tries it.
    """
    probe = entry.get("probe")
    if not probe:
        return ""
    if probe.get("ok"):
        return " ✓"
    return f" ✗ {_probe_reason(probe.get('error'))}"


def _is_playable(entry) -> bool:
    """True for a direct stream or an embedded player we know how to extract."""
    url = entry.get("url", "")
    rtype = (entry.get("type") or "").lower()
    return (
        rtype in ("m3u8", "hls", "mpd", "mp4")
        or ".m3u8" in url
        or ".m3u" in url
        or ".mpd" in url.lower()
        or "master" in url.lower()
        or player_scraper.is_supported(url)
    )


class _StreamMenu(NamedTuple):
    """One frame of the source menu, plus the index map the caller needs."""

    options: list[str]
    prompt: str
    entries: list[dict]
    back: int
    wait: int
    skipped: int


def _stream_menu(
    megaplay_results, snapshot, *, waiting, pending, live_menu
) -> _StreamMenu:
    """Build the source menu from the current search snapshot.

    Rows keep the arrival order of the search: a later link is appended, never
    inserted, so the highlighted entry does not jump while the search or the
    link checks finish. The verdict of the background check is appended as a
    suffix instead of moving or hiding the row.
    """
    results = _merge_streams(megaplay_results, snapshot)
    entries = [entry for entry in results if _is_playable(entry)]
    rows = [
        f"{entry['source']} - {entry['quality']} ({entry['type']})"
        f"{_probe_marker(entry)}"
        for entry in entries
    ]

    checking = sum(
        1 for entry in snapshot if _is_direct(entry) and "probe" not in entry
    )
    unreachable = sum(1 for entry in entries if _probe_failed(entry))
    if not entries and waiting:
        status = ["searching…"]
    else:
        status = [f"{len(entries)} source(s)"]
        if checking:
            status.append(f"{checking} checking")
        if unreachable:
            status.append(f"{unreachable} unreachable")
        if waiting:
            status.append(f"{pending} still loading")
    prompt = f"📺 Select Stream · {' · '.join(status)}:"

    options = list(rows)
    wait_index = -1
    if not live_menu and waiting:
        wait_index = len(options)
        options.append(f"⏳ Wait for the remaining sources ({pending} still loading)")
    options.append("← Back")

    return _StreamMenu(
        options=options,
        prompt=prompt,
        entries=entries,
        back=len(options) - 1,
        wait=wait_index,
        skipped=len(results) - len(entries),
    )


def _flow_goldenanime_stream(
    title: str, anilist_id: int, episode: int, cover_url: str = None
):
    """Common logic for searching streams, subtitles, and playing."""
    mappings = _mapping_ids(anilist_id)
    mapped_imdb = mappings.get("imdbId")
    if mapped_imdb and not str(mapped_imdb).startswith("tt"):
        mapped_imdb = f"tt{mapped_imdb}"
    mapped_anidb = mappings.get("anidbId")
    mapping_format = (mappings.get("format") or mappings.get("type") or "").upper()
    is_movie = True if mapping_format == "MOVIE" else (False if mapping_format else None)
    default_season = _mapping_season(mappings)

    print_info("Searching for streams...")
    # Progressive: the first streams show up as soon as an instance answers,
    # and the slower ones are appended while the user browses or watches.
    # Every direct link is checked in the background so the menu can flag the
    # ones that will not play, without ever reordering or hiding a row.
    search = goldenanime.progressive_search(
        anilist_id, episode, probe=probe_direct_stream
    )
    search.start()

    # MegaPlay only needs the AniList id, so it keeps working when the
    # aggregator's providers answer with errors. It runs while the workers
    # above are already busy.
    try:
        megaplay_results = megaplay_extractor.streams(anilist_id, episode)
    except Exception:  # noqa: BLE001 - optional source
        megaplay_results = []
    if not megaplay_results:
        print_info("[dim]MegaPlay has no entry for this title.[/dim]")

    search.wait_for_first(FIRST_STREAM_WAIT)

    # ``state`` holds what the last rendered frame maps to: a live menu can
    # rebuild the list after this scope, so the index it returns must be read
    # against the entries of that same frame.
    live_menu = supports_live_refresh()
    state = {"entries": [], "back": 0, "wait": -1, "skipped": 0}

    def build_menu():
        menu = _stream_menu(
            megaplay_results,
            search.snapshot(),
            waiting=not search.is_done(),
            pending=search.pending(),
            live_menu=live_menu,
        )
        state.update(
            entries=menu.entries,
            back=menu.back,
            wait=menu.wait,
            skipped=menu.skipped,
        )
        return menu.options, menu.prompt

    reported_skipped = 0
    while True:
        options, prompt = build_menu()
        entries = state["entries"]
        waiting = not search.is_done()

        if not entries and not waiting:
            print_warning(
                "No supported streams found (no direct M3U8 or recognised players)."
            )
            pause()
            return

        if not entries and not live_menu:
            # No live menu to fill itself: block and report the sources as
            # they land instead of showing a list with a single "Back" row.
            _wait_for_remaining(search)
            continue

        if state["skipped"] and state["skipped"] != reported_skipped:
            reported_skipped = state["skipped"]
            print_info(f"[dim]Skipped {reported_skipped} unsupported stream(s).[/dim]")

        choice_idx = select_from_list(
            options, prompt, refresher=build_menu if live_menu else None
        )

        # Indices are stable by construction: sources, then the optional
        # "wait" row, then "Back".
        if choice_idx == state["back"]:
            search.stop()
            return
        if choice_idx == state["wait"]:
            _wait_for_remaining(search)
            continue

        selection = state["entries"][choice_idx]

        if _probe_failed(selection):
            print_warning(
                f"{selection['source']} did not answer the check "
                f"({_probe_reason(selection['probe'].get('error'))}); "
                "trying anyway."
            )

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
                    "← Back",
                ],
                "The stream has embedded subtitle tracks (language picked in the player):",
            )
            if use_embedded == 0:
                subtitle_tracks = embedded_tracks
            elif use_embedded == 2:
                continue

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
                ["Yes", "No", "← Back"], f"Search for {lang_name} subtitles?"
            )
            if want_subs == 2:
                continue
            if want_subs == 0:
                # The AniList mapping is authoritative when present: it knows
                # the IMDB/AniDB ids and whether the entry is a movie, so no
                # Cinemeta guessing and no fake season menu.
                imdb_id = mapped_imdb
                anidb_id = mapped_anidb
                movie = is_movie
                if not imdb_id and not anidb_id and search_title:
                    imdb_id, resolved_movie = resolve_imdb_id(
                        search_title, is_movie
                    )
                    if is_movie is None:
                        movie = bool(resolved_movie)
                elif not imdb_id and not anidb_id:
                    imdb_id = get_user_input(
                        "Enter IMDB ID manually (e.g. tt0388629, leave blank to skip)"
                    )

                if imdb_id or anidb_id:
                    season = None
                    sub_episode = None
                    if not movie:
                        season = _ask_subtitle_season(default_season)
                        if season is None:
                            continue
                        sub_episode = _subtitle_episode(
                            episode, season, default_season, mappings
                        )
                        if sub_episode != episode:
                            print_info(
                                f"TVDB numbering: S{season:02d}E{sub_episode:02d} "
                                f"(AniList episode {episode})"
                            )

                    print_info(f"Searching for {lang_name} subtitles...")
                    subs = subtitle_extractor.search(
                        imdb_id=imdb_id,
                        season=season,
                        episode=sub_episode,
                        lang_filter=user_lang,
                        anidb_id=anidb_id,
                    )

                    if subs:
                        shown = subs[:6]
                        sub_choices = [describe_subtitle(s) for s in shown] + [
                            "← Back",
                            "None",
                        ]
                        sub_idx = select_from_list(sub_choices, "📝 Select Subtitle:")
                        if sub_idx < len(shown):
                            subtitle_tracks = [shown[sub_idx]]
                            print_info(
                                f"Selected subtitle from: {shown[sub_idx]['source']}"
                            )
                        elif sub_idx == len(shown):
                            continue
                    else:
                        print_warning(f"No {lang_name} subtitles found.")

        print_info(f"Loading stream from [cyan]{selection['source']}[/cyan]...")

        headers = selection.get("headers") or {"Referer": goldenanime.referer + "/"}

        display_title = title if title else f"AniList ID {anilist_id}"

        final_url = selection["url"]

        selection_type = selection["type"].lower()
        is_direct = (
            selection_type in ("m3u8", "mpd", "mp4")
            or "m3u8" in final_url
            or ".mpd" in final_url.lower()
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
            return True

        # Playback failed: let the user pick another source (many provider
        # links are dead or expired), or go back.
        change_source = select_from_list(
            ["Try another source", "← Back"],
            "Playback failed or was cancelled. What would you like to do?",
        )
        if change_source == 1:
            pause()
            return False


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
