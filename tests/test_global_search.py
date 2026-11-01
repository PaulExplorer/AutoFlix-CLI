import pytest

from autoflix_cli.scraping.objects import SearchResult
from autoflix_cli.handlers import global_search as gs


def _result(title, url="https://example.test/x"):
    return SearchResult(title=title, url=url, img="", genres=[])


@pytest.fixture
def sources():
    return [
        {"key": "p1", "label": "P1"},
        {"key": "p2", "label": "P2"},
        {"key": "p3", "label": "P3"},
    ]


class TestSimilarity:
    def test_exact_match_scores_highest(self):
        assert gs.similarity("Naruto", "naruto!") > gs.similarity("Naruto", "Naruto Shippuden")

    def test_substring_beats_partial_similarity(self):
        assert gs.similarity("Naruto", "Naruto Shippuden") > gs.similarity("Naruto", "Ousama Ranking")

    def test_accents_and_punctuation_are_ignored(self):
        assert gs.similarity("demon slayer", "Démon-Slayer!") == 3.0

    def test_empty_inputs(self):
        assert gs.similarity("", "Naruto") == 0.0
        assert gs.similarity("Naruto", "") == 0.0


class TestRankResults:
    def test_ranking_across_providers(self, sources):
        outcomes = [
            ("p1", [_result("Ousama Ranking")]),
            ("p2", [_result("Naruto")]),
            ("p3", [_result("Naruto Shippuden")]),
        ]
        items = gs.rank_results("naruto", outcomes, sources)
        assert [it["result"].title for it in items] == [
            "Naruto",
            "Naruto Shippuden",
            "Ousama Ranking",
        ]
        assert items[0]["label"] == "P2"

    def test_ties_keep_provider_order(self, sources):
        outcomes = [
            ("p2", [_result("Xyz")]),
            ("p1", [_result("Xyz")]),
        ]
        items = gs.rank_results("abc", outcomes, sources)
        assert items[0]["provider"] == "p1"
        assert items[1]["provider"] == "p2"

    def test_identical_results_within_a_provider_are_deduped(self, sources):
        outcomes = [("p1", [_result("Same Title"), _result("Same Title")])]
        items = gs.rank_results("title", outcomes, sources)
        assert len(items) == 1

    def test_same_title_from_different_providers_is_kept(self, sources):
        title = "Same Title"
        outcomes = [("p1", [_result(title)]), ("p2", [_result(title)])]
        items = gs.rank_results("title", outcomes, sources)
        assert {it["provider"] for it in items} == {"p1", "p2"}

    def test_failed_and_empty_providers_are_skipped(self, sources):
        outcomes = [
            ("p1", RuntimeError("boom")),
            ("p2", []),
            ("p3", [_result("Naruto")]),
        ]
        items = gs.rank_results("naruto", outcomes, sources)
        assert [it["provider"] for it in items] == ["p3"]


class TestSearchAll:
    def test_preserves_provider_order_and_catches_errors(self):
        def ok(query):
            return [_result(f"{query}-hit")]

        def boom(query):
            raise RuntimeError("boom")

        srcs = [
            {"key": "p1", "label": "P1", "search": ok},
            {"key": "p2", "label": "P2", "search": boom},
            {"key": "p3", "label": "P3", "search": ok},
        ]
        outcomes = gs.search_all("naruto", srcs)
        assert [key for key, _ in outcomes] == ["p1", "p2", "p3"]
        assert isinstance(outcomes[0][1], list)
        assert outcomes[0][1][0].title == "naruto-hit"
        assert isinstance(outcomes[1][1], Exception)
        assert isinstance(outcomes[2][1], list)

    def test_empty_sources(self):
        assert gs.search_all("naruto", []) == []


class TestSourceSelection:
    def test_filters_by_allowed_keys(self):
        specs = gs._select_sources({"anime_sama", "coflix"})
        assert {s["key"] for s in specs} == {"anime_sama", "coflix"}

    def test_unknown_keys_are_ignored(self):
        assert gs._select_sources({"nope"}) == []
