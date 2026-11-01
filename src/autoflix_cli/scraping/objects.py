from dataclasses import dataclass


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
