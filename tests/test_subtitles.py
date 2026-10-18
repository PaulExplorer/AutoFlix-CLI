"""Offline tests for the subtitle package (no network)."""

from dataclasses import replace

import pytest

from autoflix_cli.scraping.subtitles import providers
from autoflix_cli.scraping.subtitles.extractor import SubtitleExtractor
from autoflix_cli.scraping.subtitles.language_tags import (
    language_label,
    languages_match,
    normalize_language,
)
from autoflix_cli.scraping.subtitles.matching import guess_format, is_batch, matches_episode
from autoflix_cli.scraping.subtitles.models import Subtitle, SubtitleQuery
from autoflix_cli.scraping.subtitles.providers import (
    AnimeToshoProvider,
    StremioSubtitleProvider,
    SubtitleProvider,
)


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("fr", "fr"),
        ("FR", "fr"),
        ("French", "fr"),
        ("fre", "fr"),
        ("fra", "fr"),
        ("pt-BR", "pt"),
        ("por", "pt"),
        ("zh-Hant", "zh"),
        ("chi", "zh"),
        ("eng", "en"),
        ("English", "en"),
        ("", None),
        (None, None),
        ("klingon", None),
    ],
)
def test_normalize_language(raw, expected):
    assert normalize_language(raw) == expected


def test_languages_match_avoids_substring_false_positives():
    # The old code matched languages with substring checks: "en" in "french"
    # is True and wrongly accepted English subtitles for a French request.
    assert languages_match("french", "en") is False
    assert languages_match("fr", "en") is False
    assert languages_match("eng", "en") is True
    assert languages_match("French", "fr") is True
    # No preference means everything matches.
    assert languages_match("xx", None) is True


def test_language_label():
    assert language_label("fr") == "French"
    assert language_label(None) == "Unknown"


@pytest.mark.parametrize(
    "name,episode,season,expected",
    [
        ("Show.S01E05.1080p", 5, 1, True),
        ("Show.1x05", 5, 1, True),
        ("Show - 06 -", 5, 1, False),
        ("Show - 05 -", 5, 1, True),
        ("Show [05]", 5, None, True),
        ("1080p", 5, None, False),
        ("Show.S01E12", 2, 1, False),
        ("", 5, 1, False),
    ],
)
def test_matches_episode(name, episode, season, expected):
    assert matches_episode(name, episode, season) is expected


def test_matches_episode_without_number():
    assert matches_episode("anything", None) is False


@pytest.mark.parametrize(
    "name,expected",
    [("Show S01", True), ("Show COMPLETE", True), ("Show.E05", False)],
)
def test_is_batch(name, expected):
    assert is_batch(name) is expected


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://x/eng.ass", "ass"),
        ("https://x/sub.srt?token=1", "srt"),
        ("https://x/download/123", "srt"),
        ("https://x/fr.vtt#frag", "vtt"),
    ],
)
def test_guess_format(url, expected):
    assert guess_format(url) == expected


def test_stremio_provider_builds_scoped_series_url(monkeypatch):
    calls = []

    def fake_fetch_json(url, session=None):
        calls.append(url)
        return {
            "subtitles": [
                {"lang_code": "fr", "title": "Movie.FR", "url": "https://x/fr.srt"},
                {"lang": "fre", "movieReleaseName": "Movie VF", "url": "https://x/vf.srt"},
                {"url": ""},  # dropped: no url
            ]
        }

    monkeypatch.setattr(providers, "fetch_json", fake_fetch_json)
    provider = StremioSubtitleProvider(
        "Homes", "https://homes.example/", priority=1, language_scoped=True
    )
    subs = provider.fetch(SubtitleQuery(imdb_id="tt1", language="fr"))

    assert calls == [
        "https://homes.example/fr|en/ai-translated=false|from=all/subtitles/movie/tt1.json"
    ]
    assert [s.language for s in subs] == ["fr", "fr"]
    assert subs[0].priority == 1
    assert subs[1].label == "French"


def test_stremio_provider_bare_series_url(monkeypatch):
    calls = []
    monkeypatch.setattr(
        providers, "fetch_json", lambda url, session=None: calls.append(url) or {"subtitles": []}
    )
    provider = StremioSubtitleProvider("Stremio", "https://strem.example", priority=2)
    provider.fetch(SubtitleQuery(imdb_id="tt2", season=1, episode=3))
    assert calls == ["https://strem.example/subtitles/series/tt2:1:3.json"]


def test_stremio_provider_uses_default_languages_without_preference(monkeypatch):
    calls = []
    monkeypatch.setattr(
        providers, "fetch_json", lambda url, session=None: calls.append(url) or {"subtitles": []}
    )
    provider = StremioSubtitleProvider(
        "Homes",
        "https://homes.example",
        language_scoped=True,
        default_languages=("en", "fr"),
    )
    provider.fetch(SubtitleQuery(imdb_id="tt1"))
    assert calls == [
        "https://homes.example/en|fr/ai-translated=false|from=all/subtitles/movie/tt1.json"
    ]


def test_stremio_provider_swallows_upstream_errors(monkeypatch):
    def boom(url, session=None):
        raise RuntimeError("cloudflare")

    monkeypatch.setattr(providers, "fetch_json", boom)
    provider = StremioSubtitleProvider("Stremio", "https://strem.example")
    assert provider.fetch(SubtitleQuery(imdb_id="tt2")) == []


def test_animetosho_provider_parses_subtitle_attachments(monkeypatch):
    def fake_fetch_json(url, session=None):
        if "t=search" in url:
            return [{"id": 1, "torrent_name": "Show - 05 [1080p]"}]
        if "show=torrent" in url:
            return {
                "files": [
                    {
                        "name": "Show - 05.mkv",
                        "attachments": [
                            {
                                "type": "subtitle",
                                "url": "https://a/eng.ass",
                                "info": {
                                    "language_code": "eng",
                                    "language": "English",
                                    "format": "ASS",
                                    "name": "Full",
                                },
                            },
                            {"type": "font", "url": "https://a/font.ttf"},
                        ],
                    }
                ]
            }
        return {}

    monkeypatch.setattr(providers, "fetch_json", fake_fetch_json)
    provider = AnimeToshoProvider("https://feed.example")
    subs = provider.fetch(SubtitleQuery(anidb_id=99, season=1, episode=5))

    assert len(subs) == 1
    assert subs[0].language == "en"
    assert subs[0].fmt == "ass"
    assert subs[0].url == "https://a/eng.ass"


def test_animetosho_provider_needs_anidb_id():
    provider = AnimeToshoProvider("https://feed.example")
    assert provider.fetch(SubtitleQuery(imdb_id="tt1", episode=1)) == []


class _FakeProvider(SubtitleProvider):
    def __init__(self, name, priority, subtitles):
        super().__init__(None)
        self.name = name
        self.priority = priority
        self._subtitles = subtitles

    def fetch(self, query):
        # Real providers stamp their own priority onto each Subtitle.
        return [replace(sub, priority=self.priority) for sub in self._subtitles]


class _BrokenProvider(SubtitleProvider):
    name = "Broken"

    def fetch(self, query):
        raise RuntimeError("upstream down")


def test_extractor_filters_by_language_and_returns_mappings():
    extractor = SubtitleExtractor(
        [
            _FakeProvider(
                "A",
                1,
                [
                    Subtitle(url="u-fr", source="A", language="fr", label="French", title="a"),
                    Subtitle(url="u-en", source="A", language="en", label="English", title="b"),
                ],
            )
        ]
    )
    results = extractor.search(imdb_id="tt1", lang_filter="French")

    assert [r["url"] for r in results] == ["u-fr"]
    assert results[0]["lang"] == "fr"
    assert results[0]["label"] == "French"
    assert results[0]["format"] == "srt"


def test_extractor_ranks_by_priority_and_is_deterministic():
    low = _FakeProvider("Low", 5, [Subtitle(url="z", source="Low", language="fr", title="z")])
    high = _FakeProvider("High", 1, [Subtitle(url="a", source="High", language="fr", title="m")])

    first = SubtitleExtractor([low, high]).search("tt1", lang_filter="fr")
    second = SubtitleExtractor([low, high]).search("tt1", lang_filter="fr")

    assert [r["source"] for r in first] == ["High", "Low"]
    assert first == second  # no more random.shuffle()


def test_extractor_dedupes_keeping_most_trusted():
    worse = _FakeProvider(
        "Worse", 9, [Subtitle(url="same", source="Worse", language="fr", title="t")]
    )
    best = _FakeProvider("Best", 1, [Subtitle(url="same", source="Best", language="fr", title="t")])

    results = SubtitleExtractor([worse, best]).search("tt1", lang_filter="fr")

    assert len(results) == 1
    assert results[0]["source"] == "Best"


def test_extractor_isolates_a_broken_provider():
    extractor = SubtitleExtractor(
        [
            _BrokenProvider(),
            _FakeProvider("Ok", 1, [Subtitle(url="u", source="Ok", language="fr")]),
        ]
    )
    assert [r["url"] for r in extractor.search("tt1", lang_filter="fr")] == ["u"]


def test_global_extractor_is_importable():
    from autoflix_cli.scraping.subtitles import subtitle_extractor

    assert isinstance(subtitle_extractor, SubtitleExtractor)
