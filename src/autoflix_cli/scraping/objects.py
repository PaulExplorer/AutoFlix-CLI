class SearchResult:
    def __init__(self, title: str, url: str, img: str, genres: list[str]):
        self.title = title
        self.url = url
        self.img = img
        self.genres = genres

    def __str__(self):
        return f"SearchResult(title='{self.title}', url='{self.url}', img='{self.img}', genres={self.genres})"

    def __repr__(self):
        return str(self)


class Player:
    def __init__(self, name: str, url: str):
        self.name = name
        self.url = url

    def __str__(self):
        return f"Player(name='{self.name}', url='{self.url}')"

    def __repr__(self):
        return str(self)


class WiflixMovie:
    def __init__(
        self,
        title: str,
        url: str,
        img: str,
        genres: list[str],
        year: int,
        origin: str,
        authors: str,
        duration: str,
        players: list[Player],
    ):
        self.title = title
        self.url = url
        self.img = img
        self.genres = genres
        self.year = year
        self.origin = origin
        self.authors = authors
        self.duration = duration
        self.players = players

    def __str__(self):
        return f"WiflixMovie(title='{self.title}', url='{self.url}', img='{self.img}', genres={self.genres}, year={self.year}, origin='{self.origin}', authors='{self.authors}', duration='{self.duration}', players={self.players})"

    def __repr__(self):
        return str(self)


class Episode:
    def __init__(self, title: str, players: list[Player]):
        self.title = title
        self.players = players

    def __str__(self):
        return f"Episode(title='{self.title}', players={self.players})"

    def __repr__(self):
        return str(self)


class WiflixSeriesSeason:
    def __init__(
        self,
        title: str,
        season: str,
        url: str,
        img: str,
        genres: list[str],
        year: int,
        origin: str,
        authors: str,
        duration: str,
        episodes: dict[str, list[Episode]],
    ):
        self.title = title
        self.season = season
        self.url = url
        self.img = img
        self.genres = genres
        self.year = year
        self.origin = origin
        self.authors = authors
        self.duration = duration
        self.episodes = episodes

    def __str__(self):
        return f"WiflixSeriesSeason(title='{self.title}', season='{self.season}', url='{self.url}', img='{self.img}', genres={self.genres}, year={self.year}, origin='{self.origin}', authors='{self.authors}', duration='{self.duration}', episodes={self.episodes})"

    def __repr__(self):
        return str(self)


class SamaSeason:
    def __init__(
        self, title: str, url: str, lang: list[str], episodes: dict[str, list[Episode]]
    ):
        self.title = title
        self.url = url
        self.lang = lang
        self.episodes = episodes

    def __str__(self):
        return f"SamaSeason(title='{self.title}', url='{self.url}', lang={self.lang}, episodes={self.episodes})"

    def __repr__(self):
        return str(self)


class SeasonAccess:
    def __init__(self, title: str, url: str):
        self.title = title
        self.url = url

    def __str__(self):
        return f"SeasonAccess(title='{self.title}', url='{self.url}')"

    def __repr__(self):
        return str(self)


class EpisodeAccess:
    def __init__(self, title: str, url: str):
        self.title = title
        self.url = url

    def __str__(self):
        return f"EpisodeAccess(title='{self.title}', url='{self.url}')"

    def __repr__(self):
        return str(self)


class SamaSeries:
    def __init__(
        self,
        title: str,
        url: str,
        img: str,
        genres: list[str],
        seasons: list[SeasonAccess],
    ):
        self.title = title
        self.url = url
        self.img = img
        self.genres = genres
        self.seasons = seasons

    def __str__(self):
        return f"SamaSeries(title='{self.title}', url='{self.url}', img='{self.img}', genres={self.genres}, seasons={self.seasons})"

    def __repr__(self):
        return str(self)


class CoflixMovie:
    def __init__(
        self,
        title: str,
        url: str,
        img: str,
        genres: list[str],
        year: int,
        players: list[Player],
    ):
        self.title = title
        self.url = url
        self.img = img
        self.genres = genres
        self.year = year
        self.players = players

    def __str__(self):
        return f"CoflixMovie(title='{self.title}', url='{self.url}', img='{self.img}', genres={self.genres}, year={self.year}, players={self.players})"

    def __repr__(self):
        return str(self)


class CoflixSeries:
    def __init__(
        self,
        title: str,
        url: str,
        img: str,
        genres: list[str],
        seasons: list[SeasonAccess],
    ):
        self.title = title
        self.url = url
        self.img = img
        self.genres = genres
        self.seasons = seasons

    def __str__(self):
        return f"SamaSeries(title='{self.title}', url='{self.url}', img='{self.img}', genres={self.genres}, seasons={self.seasons})"

    def __repr__(self):
        return str(self)


class CoflixSeason:
    def __init__(self, title: str, url: str, episodes: list[EpisodeAccess]):
        self.title = title
        self.url = url
        self.episodes = episodes

    def __str__(self):
        return f"SamaSeason(title='{self.title}', url='{self.url}', episodes={self.episodes})"

    def __repr__(self):
        return str(self)
