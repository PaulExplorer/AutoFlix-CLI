from typing import Callable, List, Optional


class ProviderRegistry:
    def __init__(self):
        self.providers = []

    def register(
        self,
        name: str,
        handler: Callable,
        supported_languages: Optional[List[str]] = None,
    ):
        """
        Register a streaming provider.

        :param name: Display name of the provider (e.g. '🎌 Anime-Sama').
        :param handler: The function to execute when this provider is chosen.
        :param supported_languages: List of languages ('fr', 'en', etc.). None means all languages are supported.
        """
        self.providers.append(
            {
                "name": name,
                "handler": handler,
                "supported_languages": supported_languages,
            }
        )

    def get_providers(self, target_language: Optional[str] = None) -> List[dict]:
        """
        Get all providers that support the target language.
        If target_language is None, returns all providers.
        """
        if not target_language:
            return self.providers

        filtered = []
        for p in self.providers:
            # If supported_languages is None, it supports everything
            if (
                p["supported_languages"] is None
                or target_language in p["supported_languages"]
            ):
                filtered.append(p)

        return filtered


# Global singleton instance
registry = ProviderRegistry()
