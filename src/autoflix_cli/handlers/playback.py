from ..cli_utils import (
    select_from_list,
    print_info,
    print_warning,
    print_error,
)
from ..player_manager import play_video
from ..tracker import tracker
from ..scraping import player


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

    supported_players = [p for p in episode.players if player.is_supported(p.url)]
    if not supported_players:
        print_warning("No supported players found.")
        return False

    # Default headers if not provided
    if headers is None:
        headers = {}

    while True:
        # Player Selection Menu
        player_options = [
            f"{p.name} : {p.url.split('/')[2].split('.')[-2]}"
            for p in supported_players
        ]
        player_options.append("← Back")

        player_idx = select_from_list(
            player_options,
            "🎮 Select Player:",
        )

        if player_idx == len(supported_players):  # Back selected
            return False

        selected_player = supported_players[player_idx]

        # Construct title for player window
        window_title = f"{series_title} - {season_title} - {episode.title}"

        success = play_video(
            selected_player.url,
            headers=headers,
            title=window_title,
        )

        if success:
            # Save Local Progress
            # Note: tracker.save_progress handles _to_relative conversion internally if we pass absolute URLs,
            # but to match existing pattern, we pass whatever we got.
            # Ideally verify urls are absolute before passing if possible,
            # but tracker is robust.

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
