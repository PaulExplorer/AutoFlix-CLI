import re

from ..cli_utils import (
    select_from_list,
    print_info,
    print_warning,
    print_success,
    print_error,
)
from ..tracker import tracker
from ..anilist import anilist_client


def _update_anilist_progress(provider_name, series, season, selected_episode):
    # --- AniList Progress Update ---
    anilist_token = tracker.get_anilist_token()
    if not anilist_token:
        return

    # Try to extract episode number
    episode_num = 1
    match = re.search(r"(\d+)", selected_episode.title)
    if match:
        episode_num = int(match.group(1))

    # Check if we have a mapping
    media_id = tracker.get_anilist_mapping(provider_name, series.title, season.title)

    if not media_id:
        # Ask user if they want to link
        link_choice = select_from_list(
            ["Yes", "No"],
            f"Link '{series.title}' to AniList for auto-tracking?",
        )
        if link_choice == 0:
            results = anilist_client.search_media(series.title)
            if results:
                media_options = [
                    f"{m['title']['english'] or m['title']['romaji']} ({m['seasonYear']})"
                    for m in results
                ] + ["Cancel"]
                m_idx = select_from_list(media_options, "Select AniList Match:")
                if m_idx < len(results):
                    media_id = results[m_idx]["id"]
                    tracker.set_anilist_mapping(
                        provider_name, series.title, media_id, season.title
                    )
                    print_success(
                        f"Linked to {results[m_idx]['title']['english'] or results[m_idx]['title']['romaji']}!"
                    )
            else:
                print_warning("No matches found on AniList.")

    if media_id:
        # Update progress with overflow detection
        print_info(f"Updating AniList to episode {episode_num}...")
        anilist_client.set_token(anilist_token)

        # Fetch media details to check total episodes
        media_details = anilist_client.get_media_with_relations(media_id)

        if (
            media_details
            and media_details.get("episodes")
            and episode_num > media_details["episodes"]
        ):
            total_eps = media_details["episodes"]
            print_warning(
                f"Episode {episode_num} exceeds max episodes ({total_eps}) for this AniList entry."
            )

            # Check for SEQUEL relation
            sequel = None
            relations = media_details.get("relations", {}).get("edges", [])
            for rel in relations:
                if rel["relationType"] == "SEQUEL" and rel["node"]["format"] in [
                    "TV",
                    "ONA",
                    "MOVIE",
                ]:
                    sequel = rel["node"]
                    break

            if sequel:
                sequel_title = sequel["title"]["english"] or sequel["title"]["romaji"]
                print_info(f"Found sequel: [cyan]{sequel_title}[/cyan]")

                if (
                    select_from_list(
                        ["Yes", "No"],
                        f"Switch AniList mapping to sequel '{sequel_title}'?",
                    )
                    == 0
                ):
                    # Calculate new relative episode number?
                    new_ep_num = episode_num
                    if episode_num > total_eps:
                        new_ep_num = episode_num - total_eps

                    print_info(
                        f"Updating mapping to use Episode {new_ep_num} on new entry..."
                    )
                    tracker.set_anilist_mapping(
                        provider_name, series.title, sequel["id"], season.title
                    )
                    media_id = sequel["id"]
                    episode_num = new_ep_num

        if anilist_client.update_progress(media_id, episode_num):
            print_success("AniList updated!")
        else:
            print_error("Failed to update AniList.")
