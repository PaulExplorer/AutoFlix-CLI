"""Keyless subtitle discovery for AutoFlix-CLI.

All sources are public endpoints that need no API key:

* OpenSubtitles via the stremio.homes Stremio add-on;
* OpenSubtitles via the legacy strem.io bridge;
* AnimeTosho (embedded fansub tracks, keyed by AniDB id).

``subtitle_extractor.search(...)`` remains the public entry point and returns
a list of dictionaries sorted by order of confidence.
"""

from .extractor import SubtitleExtractor, default_providers, subtitle_extractor
from .models import Subtitle, SubtitleQuery
from .providers import (
    AnimeToshoProvider,
    StremioSubtitleProvider,
    SubtitleProvider,
)

__all__ = [
    "SubtitleExtractor",
    "subtitle_extractor",
    "default_providers",
    "Subtitle",
    "SubtitleQuery",
    "SubtitleProvider",
    "StremioSubtitleProvider",
    "AnimeToshoProvider",
]
