from ..cli_utils import (
    select_from_list,
    print_info,
    print_warning,
    print_error,
    print_success
)
from ..player_manager import play_video
from ..tracker import tracker
from ..scraping import player
from ..scraping.player import PLAYER_EXTRACTORS, test_all_scrapers
from ..scraping.objects import Player


def play_episode_flow(
    provider_name: str,
    series_title: str,
    season_title: str,
    episode: object,
    series_url: str,
    season_url: str,
    logo_url: str = None,
    headers: dict = None,
    anilist_callback: callable = None,
) -> bool:
    """
    Handle the playback flow for a single episode:
    1. Check for players.
    2. Ask user to select a player.
    3. Play the video.
    4. Save progress if successful.
    5. Call optional AniList callback if successful.

    Returns:
        bool: True if playback was successful, False otherwise (back/cancel).
    """

    if not episode.players:
        print_warning("No players found for this episode.")
        return False

    dev_mode = tracker.get_developer_mode()
    supported_players = [p for p in episode.players if player.is_supported(p.url)]
    unsupported_players = [p for p in episode.players if not player.is_supported(p.url)]

    if not supported_players and not (dev_mode and unsupported_players):
        print_warning("No supported players found.")
        return False

    # Default headers if not provided
    if headers is None:
        headers = {}

    while True:
        # Player Selection Menu
        player_options = []
        player_map = []  # maps option index -> Player object

        for p in supported_players:
            try:
                player_options.append(f"{p.name} : {p.url.split('/')[2].split('.')[-2]}")
            except:
                player_options.append(p.name)
            player_map.append(p)

        # In dev mode, show unsupported players with a clear marker
        if dev_mode and unsupported_players:
            player_options.append("")
            player_options.append("── Unsupported players (dev mode) ──")
            player_map.append(None)  # separator
            player_map.append(None)  # separator header
            for p in unsupported_players:
                try:
                    domain = p.url.split('/')[2].split('.')[-2]
                except:
                    domain = p.url
                player_options.append(f"⚠ {p.name} ({domain}) [NOT SUPPORTED]")
                player_map.append(p)

        player_options.append("← Back")

        player_idx = select_from_list(
            player_options,
            "🎮 Select Player:",
        )

        if player_idx == len(player_options) - 1:  # Back selected
            return False

        selected_player = player_map[player_idx]

        # Skip separator lines (user shouldn't land here, but guard anyway)
        if selected_player is None:
            continue

        # --- Dev mode: test unsupported players with all scrapers ---
        if not player.is_supported(selected_player.url):
            print_info(f"Testing {selected_player.name} with all available scrapers...")
            scraper_results = test_all_scrapers(selected_player.url, headers)

            if scraper_results:
                scraper_names = list(scraper_results.keys())
                print_success(f"Found {len(scraper_names)} working scraper(s): {', '.join(scraper_names)}")
                scraper_opts = [f"{name} -> {scraper_results[name]}" for name in scraper_names]
                scraper_opts.append("← Back to player selection")
                scraper_idx = select_from_list(scraper_opts, "Select scraper to use:")

                if scraper_idx == len(scraper_names):
                    continue  # back to player list

                chosen_name = scraper_names[scraper_idx]
                stream_url = scraper_results[chosen_name]
                print_info(f"Using scraper '{chosen_name}' -> {stream_url}")

                # Create a fake player with the resolved stream URL
                selected_player = Player(name=f"{selected_player.name} [dev:{chosen_name}]", url=stream_url)
            else:
                print_warning("No scraper could extract a stream from this player.")
                print_info("This player is not supported and no existing scraper works with it.")
                continue

        # Construct title for player window
        window_title = f"{series_title} - {season_title} - {episode.title}"

        success = play_video(
            selected_player.url,
            headers=headers,
            title=window_title,
        )

        if success:
            # Save Local Progress

            tracker.save_progress(
                provider=provider_name,
                series_title=series_title,
                season_title=season_title,
                episode_title=episode.title,
                series_url=series_url,
                season_url=season_url,
                episode_url=episode.url if hasattr(episode, "url") else "",
                logo_url=logo_url,
            )

            # AniList Hook
            if anilist_callback:
                anilist_callback()

            return True
        else:
            # Playback failed
            retry = select_from_list(
                ["Try another server/player", "← Back to main menu"],
                "What would you like to do?",
            )
            if retry == 1:  # Back
                return False
            # Loop continues to select list
