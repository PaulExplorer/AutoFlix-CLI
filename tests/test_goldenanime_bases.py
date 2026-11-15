"""Anivexa deployments are tried per request, not once per search.

A base can be slow, blocked for a single provider, or answer 200 with an
``{error, stack}`` payload. Each case must fall through to the next instance
instead of ending the search.
"""

from autoflix_cli.scraping.goldenanime import AnimeExtractor

EPISODES = {
    "mkissa": {
        "meta": {},
        "episodes": {
            "sub": [
                {"number": 1, "id": "watch/mkissa/1/sub/mkissa-1"},
                {"number": 2, "id": "watch/mkissa/1/sub/mkissa-2"},
            ]
        },
    }
}

WATCH_OK = {
    "sources": [{"name": "S", "url": "https://cdn/x.m3u8", "type": "hls"}]
}


def _extractor(bases=("https://a", "https://b", "https://c")):
    extractor = AnimeExtractor()
    extractor.bases = list(bases)
    return extractor


def test_render_is_no_longer_a_base():
    extractor = AnimeExtractor()

    assert extractor.bases[0] == "https://anivexa.otakunaija.name.ng"
    assert not any("onrender.com" in base for base in extractor.bases)


def test_episodes_skip_a_degraded_payload(monkeypatch):
    extractor = _extractor()
    seen = []

    def request_json(base, path, timeout=20):
        seen.append(base)
        if base == "https://a":
            return {"mkissa": {"error": "boom", "stack": "..."}}
        return EPISODES

    monkeypatch.setattr(extractor, "_request_json", request_json)

    data = extractor.get_episodes(1)

    assert seen == ["https://a", "https://b"]
    assert "mkissa" in data


def test_episodes_return_empty_when_no_base_has_a_list(monkeypatch):
    extractor = _extractor()
    monkeypatch.setattr(
        extractor,
        "_request_json",
        lambda base, path, timeout=20: {"mkissa": {"error": "boom"}},
    )

    assert extractor.get_episodes(1) == {}


def test_watch_falls_back_to_the_base_that_answers(monkeypatch):
    extractor = _extractor()
    calls = []

    def request_json(base, path, timeout=20):
        calls.append(base)
        if base == "https://a":
            return {"error": "blocked", "stack": "..."}
        return WATCH_OK

    monkeypatch.setattr(extractor, "_request_json", request_json)
    monkeypatch.setattr(extractor, "get_episodes", lambda aid: EPISODES)

    results = extractor.extract_vo(anilist_id=1, episode=1)

    assert [r["url"] for r in results] == ["https://cdn/x.m3u8"]
    assert calls == ["https://a", "https://b"]


def test_failed_provider_base_pair_is_not_retried(monkeypatch):
    extractor = _extractor()
    calls = []

    def request_json(base, path, timeout=20):
        calls.append(base)
        if base == "https://a":
            return None
        return WATCH_OK

    monkeypatch.setattr(extractor, "_request_json", request_json)
    monkeypatch.setattr(extractor, "get_episodes", lambda aid: EPISODES)

    extractor.extract_vo(anilist_id=1, episode=1)
    extractor.extract_vo(anilist_id=1, episode=2)

    assert calls == ["https://a", "https://b", "https://b"]


def test_anipm_is_part_of_the_provider_list():
    assert "anipm" in AnimeExtractor.PROVIDER_PRIORITY
