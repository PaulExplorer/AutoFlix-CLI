import json

import pytest

from autoflix_cli.scraping import anime_sama
from autoflix_cli.scraping.objects import SamaEpisode, SamaLinkContext
from autoflix_cli.scraping.utils import NoEpisodesFoundError, parse_season_page

SEASON_PAGE = """<html><body>
<script data-source="bdd">
var eps1 = ["lien:11","lien:12",""];
var eps2 = ["lien:21","lien:22","lien:23"];
var eps3 = ["","lien:32","lien:33"];
var epsMeta = {"11":["ansembed.net"],"12":["ansembed.net"]};
var epsJeton = "tok.1";
var epsOrdreFinal = true;
</script>
<script>
var languesDispo = ["vostfr"];
</script>
</body></html>"""

LEGACY_PAGE = "<html><body><h1>Anime</h1></body></html>"

LEGACY_JS = """
var eps1 = ['https://player.example/one.mp4'];
var eps2 = ['https://player.example/two.mp4'];
"""

SERIES_PAGE = """<html><body>
<h1>My Anime</h1>
<div class="oe-hero">
  <div class="oe-fond"><img src="/img/grandes/my-anime-1280.webp"></div>
  <div class="oe-affiche"><img src="https://image.tmdb.org/t/p/w342/poster.jpg"></div>
</div>
<div class="oe-genres">
  <a class="genre-pill">Action</a>
  <a class="genre-pill">Comédie</a>
</div>
</body></html>"""


class FakeResponse:
    def __init__(self, text="", status_code=200, url=None):
        self.text = text
        self.status_code = status_code
        self.url = url

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return json.loads(self.text)


class FakeScraper:
    def __init__(self, routes=None):
        self.routes = routes or {}
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        for marker, response in self.routes.items():
            if marker in url:
                return response
        return FakeResponse(status_code=404)


@pytest.fixture
def season_url():
    return "https://anime-sama.test/catalogue/x/saison1/vostfr/"


@pytest.fixture
def use_site(monkeypatch):
    monkeypatch.setattr(anime_sama, "website_origin", "https://anime-sama.test/")


def test_parse_season_page_reads_inline_block():
    page = parse_season_page(SEASON_PAGE)

    assert page is not None
    assert page.jeton == "tok.1"
    assert page.langs == ["vostfr"]
    assert page.ordre_final is True
    assert page.episodes == [
        ["lien:11", "lien:21", ""],
        ["lien:12", "lien:22", "lien:32"],
        ["", "lien:23", "lien:33"],
    ]


def test_parse_season_page_swaps_columns_when_not_final():
    page = parse_season_page(SEASON_PAGE.replace("epsOrdreFinal = true", "epsOrdreFinal = false"))

    assert page.episodes[0] == ["lien:21", "lien:11", ""]


def test_parse_season_page_returns_none_without_inline_block():
    assert parse_season_page(LEGACY_PAGE) is None


def test_language_url_replaces_trailing_language():
    assert (
        anime_sama._language_url("https://x/catalogue/y/saison1/vostfr", "vf")
        == "https://x/catalogue/y/saison1/vf"
    )
    assert (
        anime_sama._language_url("https://x/catalogue/y/saison1", "vf")
        == "https://x/catalogue/y/saison1/vf"
    )


def test_get_season_keeps_links_lazy(monkeypatch, season_url, use_site):
    fake = FakeScraper(
        {
            "saison1/vostfr": FakeResponse(
                SEASON_PAGE,
                url="https://anime-sama.test/catalogue/x/saison1/vostfr/",
            )
        }
    )
    monkeypatch.setattr(anime_sama, "scraper", fake)

    season = anime_sama.get_season(season_url, resolve_links=False)

    assert season.lang == ["vostfr"]
    episodes = season.episodes["vostfr"]
    assert len(episodes) == 3
    assert episodes[0].players == []
    assert episodes[0].links == ["lien:11", "lien:21", ""]
    # ``languesDispo`` avoids probing the other language codes.
    assert len(fake.calls) == 1


def test_get_season_fetches_advertised_languages(monkeypatch, season_url, use_site):
    multi_page = SEASON_PAGE.replace('["vostfr"]', '["vostfr","vf"]')
    vf_page = SEASON_PAGE.replace("tok.1", "tok.vf")
    fake = FakeScraper(
        {
            "saison1/vostfr": FakeResponse(
                multi_page,
                url="https://anime-sama.test/catalogue/x/saison1/vostfr/",
            ),
            "saison1/vf": FakeResponse(
                vf_page, url="https://anime-sama.test/catalogue/x/saison1/vf"
            ),
        }
    )
    monkeypatch.setattr(anime_sama, "scraper", fake)

    season = anime_sama.get_season(season_url, resolve_links=False)

    assert list(season.episodes) == ["vostfr", "vf"]
    assert season.episodes["vf"][0].link_context.jeton == "tok.vf"
    assert len(fake.calls) == 2


def test_resolve_players_resolves_and_caches(monkeypatch, season_url, use_site):
    fake = FakeScraper(
        {
            "saison1/vostfr": FakeResponse(
                SEASON_PAGE,
                url="https://anime-sama.test/catalogue/x/saison1/vostfr/",
            )
        }
    )
    monkeypatch.setattr(anime_sama, "scraper", fake)
    monkeypatch.setattr(
        anime_sama,
        "_request_link",
        lambda jeton, link_id, referer: (f"https://host/{link_id}.html", None),
    )

    season = anime_sama.get_season(season_url, resolve_links=False)
    episode = season.episodes["vostfr"][0]

    players = anime_sama.resolve_players(episode)

    assert [p.name for p in players] == ["Lecteur 1", "Lecteur 2"]
    assert [p.url for p in players] == [
        "https://host/11.html",
        "https://host/21.html",
    ]
    assert episode.players is players
    # Cached: a second call does not hit the API again.
    assert anime_sama.resolve_players(episode) is players


def test_resolve_players_skips_failures_and_duplicates(monkeypatch, use_site):
    responses = {
        "11": ("https://host/same.html", None),
        "12": (None, "absent"),
        "13": ("https://host/same.html", None),
    }
    monkeypatch.setattr(
        anime_sama,
        "_request_link",
        lambda jeton, link_id, referer: responses[link_id],
    )

    context = SamaLinkContext("https://anime-sama.test/season/", "tok")
    episode = SamaEpisode(
        "Épisode 1",
        [],
        ["lien:11", "lien:12", "lien:13"],
        context,
    )

    players = anime_sama.resolve_players(episode)

    assert [p.url for p in players] == ["https://host/same.html"]


def test_resolve_link_refreshes_expired_jeton(monkeypatch):
    seen = []

    def fake_request(jeton, link_id, referer):
        seen.append(jeton)
        if jeton == "old":
            return None, "expire"
        return f"https://host/{link_id}.html", None

    def fake_refresh(context):
        context.jeton = "new"
        return True

    monkeypatch.setattr(anime_sama, "_request_link", fake_request)
    monkeypatch.setattr(anime_sama, "_refresh_jeton", fake_refresh)

    context = SamaLinkContext("https://anime-sama.test/season/", "old")

    assert anime_sama._resolve_link("lien:7", context) == "https://host/7.html"
    assert seen == ["old", "new"]


def test_get_season_can_resolve_every_episode(monkeypatch, season_url, use_site):
    fake = FakeScraper(
        {
            "saison1/vostfr": FakeResponse(
                SEASON_PAGE,
                url="https://anime-sama.test/catalogue/x/saison1/vostfr/",
            )
        }
    )
    monkeypatch.setattr(anime_sama, "scraper", fake)
    monkeypatch.setattr(
        anime_sama,
        "_request_link",
        lambda jeton, link_id, referer: (f"https://host/{link_id}.html", None),
    )

    season = anime_sama.get_season(season_url, resolve_links=True)

    assert all(episode.players for episode in season.episodes["vostfr"])


def test_get_season_falls_back_to_legacy_episodes_js(monkeypatch, season_url, use_site):
    fake = FakeScraper(
        {
            "episodes.js": FakeResponse(LEGACY_JS),
            "saison1/vostfr": FakeResponse(
                LEGACY_PAGE,
                url="https://anime-sama.test/catalogue/x/saison1/vostfr/",
            ),
        }
    )
    monkeypatch.setattr(anime_sama, "scraper", fake)

    season = anime_sama.get_season(season_url, resolve_links=False)

    players = season.episodes["vostfr"][0].players
    assert [p.url for p in players] == [
        "https://player.example/one.mp4",
        "https://player.example/two.mp4",
    ]


def test_get_season_raises_when_nothing_is_released(monkeypatch, season_url, use_site):
    empty_page = """<html><body>
<script data-source="bdd">
var eps1 = [];
var epsJeton = "tok";
</script>
<script>
var languesDispo = ["vostfr"];
</script>
</body></html>"""
    fake = FakeScraper(
        {
            "saison1/vostfr": FakeResponse(
                empty_page,
                url="https://anime-sama.test/catalogue/x/saison1/vostfr/",
            )
        }
    )
    monkeypatch.setattr(anime_sama, "scraper", fake)

    with pytest.raises(NoEpisodesFoundError):
        anime_sama.get_season(season_url, resolve_links=False)


def test_get_series_reads_current_layout(monkeypatch, use_site):
    fake = FakeScraper(
        {
            "catalogue/x": FakeResponse(
                SERIES_PAGE, url="https://anime-sama.test/catalogue/x"
            )
        }
    )
    monkeypatch.setattr(anime_sama, "scraper", fake)

    series = anime_sama.get_series("https://anime-sama.test/catalogue/x")

    assert series.title == "My Anime"
    assert series.img == "https://image.tmdb.org/t/p/w342/poster.jpg"
    assert series.genres == ["Action", "Comédie"]
