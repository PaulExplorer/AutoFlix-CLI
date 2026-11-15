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


def test_a_degraded_payload_does_not_hide_the_other_bases(monkeypatch):
    extractor = _extractor(["https://a", "https://b"])

    def request_json(base, path, timeout=20):
        if path.startswith("/episodes/"):
            if base == "https://a":
                return {"mkissa": {"error": "boom", "stack": "..."}}
            return EPISODES
        return WATCH_OK

    monkeypatch.setattr(extractor, "_request_json", request_json)

    search = extractor.progressive_search(1, 1).start()
    search.wait(3)

    assert [r["url"] for r in search.snapshot()] == ["https://cdn/x.m3u8"]


def test_watch_falls_back_when_the_listing_base_is_blocked(monkeypatch):
    extractor = _extractor()
    calls = []

    def request_json(base, path, timeout=20):
        if path.startswith("/episodes/"):
            # Only one base lists the provider, so the ordering is fixed.
            return EPISODES if base == "https://b" else {"mkissa": {"error": "boom"}}
        calls.append(base)
        if base == "https://b":
            return {"error": "blocked", "stack": "..."}
        return WATCH_OK

    monkeypatch.setattr(extractor, "_request_json", request_json)

    results = extractor.extract_vo(anilist_id=1, episode=1)

    assert [r["url"] for r in results] == ["https://cdn/x.m3u8"]
    # The base that listed the episode is asked first; its fast failure makes
    # the other instances run in parallel.
    assert calls[0] == "https://b"
    assert set(calls) == {"https://a", "https://b", "https://c"}


def test_failed_provider_base_pair_is_not_retried(monkeypatch):
    extractor = _extractor()
    calls = []

    def request_json(base, path, timeout=20):
        if path.startswith("/episodes/"):
            return EPISODES if base == "https://b" else {"mkissa": {"error": "boom"}}
        calls.append(base)
        if base == "https://b":
            return None
        return WATCH_OK

    monkeypatch.setattr(extractor, "_request_json", request_json)

    extractor.extract_vo(anilist_id=1, episode=1)
    assert calls[0] == "https://b"
    assert ("mkissa", "https://b") in extractor._watch_failures

    calls.clear()
    extractor.extract_vo(anilist_id=1, episode=2)

    assert "https://b" not in calls


def test_anipm_is_part_of_the_provider_list():
    assert "anipm" in AnimeExtractor.PROVIDER_PRIORITY
