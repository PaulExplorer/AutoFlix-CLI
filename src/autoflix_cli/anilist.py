import json
from curl_cffi import requests
from typing import Optional, Dict, Any, List


class AniListClient:
    def __init__(self, token: Optional[str] = None):
        self.url = "https://graphql.anilist.co"
        self.token = token
        self.headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if self.token:
            self.headers["Authorization"] = f"Bearer {self.token}"

    def set_token(self, token: str):
        """Set the authorization token."""
        self.token = token
        self.headers["Authorization"] = f"Bearer {token}"

    def _query(
        self, query: str, variables: Dict[str, Any] = None
    ) -> Optional[Dict[str, Any]]:
        """Send a GraphQL query to AniList."""
        try:
            response = requests.post(
                self.url,
                json={"query": query, "variables": variables},
                headers=self.headers,
                timeout=10,
            )
            response.raise_for_status()
            data = response.json()
            if "errors" in data:
                print(f"AniList API Error: {data['errors']}")
                return None
            return data["data"]
        except Exception as e:
            print(f"Request Error: {e}")
            return None

    def validate_token(self) -> Optional[Dict[str, Any]]:
        """Check if the current token is valid and return user info."""
        query = """
        query {
            Viewer {
                id
                name
                avatar {
                    large
                }
            }
        }
        """
        data = self._query(query)
        if data and data.get("Viewer"):
            return data["Viewer"]
        return None

    def search_media(self, search: str) -> List[Dict[str, Any]]:
        """Search for an anime/manga by title."""
        query = """
        query ($search: String) {
            Page(page: 1, perPage: 10) {
                media(search: $search, type: ANIME, sort: SEARCH_MATCH) {
                    id
                    title {
                        romaji
                        english
                        native
                    }
                    coverImage {
                        medium
                    }
                    format
                    episodes
                    status
                    seasonYear
                }
            }
        }
        """
        variables = {"search": search}
        data = self._query(query, variables)
        if data and data.get("Page") and data.get("Page", {}).get("media"):
            return data["Page"]["media"]
        return []

    def get_media_status(self, media_id: int, user_id: int) -> Optional[Dict[str, Any]]:
        """Get the user's current status for a specific media."""
        query = """
        query ($mediaId: Int, $userId: Int) {
            MediaList(mediaId: $mediaId, userId: $userId) {
                id
                status
                progress
                score
            }
        }
        """
        variables = {"mediaId": media_id, "userId": user_id}
        # Note: MediaList returns 404/null if not found, we need to handle that gracefully
        try:
            data = self._query(
                query, variables
            )  # This might fail if not found depending on API behavior
            if data:
                return data.get("MediaList")
        except Exception:
            pass
        return None

    def update_progress(self, media_id: int, progress: int) -> bool:
        """Update the progress for a media item. Also sets status to CURRENT if not already."""
        query = """
        mutation ($mediaId: Int, $progress: Int, $status: MediaListStatus) {
            SaveMediaListEntry(mediaId: $mediaId, progress: $progress, status: $status) {
                id
                progress
                status
            }
        }
        """
        # We enforce status to CURRENT whenever we update progress,
        # unless it's already completed (logic could be refined)
        variables = {"mediaId": media_id, "progress": progress, "status": "CURRENT"}
        data = self._query(query, variables)
        return data is not None and "SaveMediaListEntry" in data

    def get_user_list(self, user_id: int, status: str) -> List[Dict[str, Any]]:
        """Get the user's anime list for a given status (CURRENT, PLANNING, COMPLETED, DROPPED, PAUSED)."""
        query = """
        query ($userId: Int, $status: MediaListStatus) {
            MediaListCollection(userId: $userId, type: ANIME, status: $status, sort: UPDATED_TIME_DESC) {
                lists {
                    entries {
                        mediaId
                        progress
                        status
                        score
                        media {
                            title {
                                romaji
                                english
                            }
                            coverImage {
                                medium
                            }
                            format
                            episodes
                            seasonYear
                            status
                            nextAiringEpisode {
                                episode
                                airingAt
                                timeUntilAiring
                            }
                        }
                    }
                }
            }
        }
        """
        variables = {"userId": user_id, "status": status}
        data = self._query(query, variables)
        if (
            data
            and data.get("MediaListCollection")
            and data["MediaListCollection"].get("lists")
        ):
            entries = []
            for lst in data["MediaListCollection"]["lists"]:
                entries.extend(lst.get("entries", []))
            return entries
        return []

    def get_user_watching(self, user_id: int) -> List[Dict[str, Any]]:
        """Get the user's current watching list (CURRENT)."""
        return self.get_user_list(user_id, "CURRENT")

    def get_user_planning(self, user_id: int) -> List[Dict[str, Any]]:
        """Get the user's planning list (anime à voir)."""
        return self.get_user_list(user_id, "PLANNING")

    def get_user_completed(self, user_id: int) -> List[Dict[str, Any]]:
        """Get the user's completed list."""
        return self.get_user_list(user_id, "COMPLETED")

    def get_user_dropped(self, user_id: int) -> List[Dict[str, Any]]:
        """Get the user's dropped list."""
        return self.get_user_list(user_id, "DROPPED")

    def update_status(self, media_id: int, status: str, progress: int = None) -> bool:
        """Update the status for a media item. Valid statuses: CURRENT, PLANNING, COMPLETED, DROPPED, PAUSED, REPEATING."""
        query = """
        mutation ($mediaId: Int, $status: MediaListStatus, $progress: Int) {
            SaveMediaListEntry(mediaId: $mediaId, status: $status, progress: $progress) {
                id
                progress
                status
            }
        }
        """
        variables = {"mediaId": media_id, "status": status}
        if progress is not None:
            variables["progress"] = progress
        data = self._query(query, variables)
        return data is not None and "SaveMediaListEntry" in data

    def remove_from_list(self, media_id: int) -> bool:
        """Remove a media item from the user's list by setting status to null (DELETE)."""
        query = """
        mutation ($mediaId: Int) {
            DeleteMediaListEntry(mediaId: $mediaId) {
                deleted
            }
        }
        """
        variables = {"mediaId": media_id}
        data = self._query(query, variables)
        return data is not None and data.get("DeleteMediaListEntry", {}).get("deleted", False)

    def get_media_with_relations(self, media_id: int) -> Optional[Dict[str, Any]]:
        """Get media details including episode count and relations (sequels)."""
        query = """
        query ($mediaId: Int) {
            Media(id: $mediaId) {
                id
                title {
                    romaji
                    english
                }
                episodes
                relations {
                    edges {
                        relationType
                        node {
                            id
                            title {
                                romaji
                                english
                            }
                            episodes
                            format
                        }
                    }
                }
            }
        }
        """
        variables = {"mediaId": media_id}
        data = self._query(query, variables)
        if data and data.get("Media"):
            return data["Media"]
        return None


# Global instance
anilist_client = AniListClient()
