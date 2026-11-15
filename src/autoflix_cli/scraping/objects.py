from dataclasses import dataclass, field
from typing import Optional


@dataclass
class SearchResult:

    # paramètres obligatoires
    title: str
    url: str
    img: str
    genres: list[str]

    # paramètres facultatifs (toujours après les obligatoires)
    id: str = ""

@dataclass
class Player:
    name: str
    url: str


@dataclass
class Episode:
    title: str
    players: list[Player]


@dataclass
class SamaLinkContext:
    """State shared by the episodes of one Anime-Sama season page.

    ``jeton`` is the page token required by ``/api/lien.php`` and can be
    refreshed in place when it expires.
    """

    referer: str
    jeton: str


@dataclass
class SamaEpisode(Episode):
    """Episode whose players are resolved on demand.

    Anime-Sama season pages only carry ``lien:<id>`` references. Resolving
    every episode at once would hit the API rate limit, so the references
    stay here until the episode is selected.
    """

    links: list[Optional[str]] = field(default_factory=list)
    link_context: Optional[SamaLinkContext] = None


@dataclass
class SamaSeasonPage:
    """Episode references parsed from an Anime-Sama season page.

    ``episodes`` holds one list per episode, with the raw entry of each
    player column (empty string when that player has no link).
    """

    episodes: list[list[str]]
    jeton: str = ""
    langs: list[str] = field(default_factory=list)
    ordre_final: bool = True


@dataclass
class SamaSeason:
    title: str
    url: str
    lang: list[str]
    episodes: dict[str, list[Episode]]


@dataclass
class SeasonAccess:
    title: str
    url: str


@dataclass
class EpisodeAccess:
    title: str
    url: str


@dataclass
class SamaSeries:
    title: str
    url: str
    img: str
    genres: list[str]
    seasons: list[SeasonAccess]


@dataclass
class ArkSeason:
    id: str
    title: str
    episodes: list[Episode]


@dataclass
class ArkSeries:
    id: str
    title: str
    img: str
    genres: list[str]
    seasons: list[ArkSeason]


@dataclass
class ArkMovie:
    id: str
    title: str
    img: str
    genres: list[str]
    players: list[Player]


@dataclass
class CoflixMovie:
    title: str
    url: str
    img: str
    genres: list[str]
    players: list[Player]


@dataclass
class CoflixSeason:
    title: str
    episodes: list[EpisodeAccess]


@dataclass
class CoflixSeries:
    title: str
    url: str
    img: str
    genres: list[str]
    seasons: list[CoflixSeason]


@dataclass
class FrenchStreamMovie:
    title: str
    url: str
    img: str
    genres: list[str]
    players: list[Player]


@dataclass
class FrenchStreamSeason:
    title: str
    url: str
    episodes: dict[str, list[Episode]]
