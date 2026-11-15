"""Streams must appear while the search is still running.

The menu reads ``snapshot()`` from the main thread, so a slow instance or a
blocked provider must not hide the sources that already answered. The
blocking ``extract_vo`` keeps the old behaviour (wait, then rank).
"""

import time

from autoflix_cli.scraping.goldenanime import AnimeExtractor


def _episodes(provider):
    return {
        provider: {
            "meta": {},
            "episodes": {
                "sub": [
                    {
                        "number": 1,
                        "id": f"watch/{provider}/1/sub/{provider}-1",
                    }
                ]
            },
        }
    }


def _watch(url, priority=1):
    return {
        "sources": [
            {"name": "S", "url": url, "type": "hls", "priority": priority}
        ]
    }


def _extractor(bases):
    extractor = AnimeExtractor()
    extractor.bases = list(bases)
    return extractor


def test_streams_show_up_before_the_slow_base_answers(monkeypatch):
    extractor = _extractor(["https://fast", "https://slow"])

    def request_json(base, path, timeout=20):
        if path.startswith("/episodes/"):
            if base == "https://fast":
                return _episodes("mkissa")
            time.sleep(0.6)
            return _episodes("animegg")
        if "mkissa" in path:
            return _watch("https://cdn/mkissa.m3u8")
        return _watch("https://cdn/animegg.m3u8")

    monkeypatch.setattr(extractor, "_request_json", request_json)

    search = extractor.progressive_search(1, 1).start()

    assert search.wait_for_first(0.3) is True
    # The fast base answered; the slow one is still working.
    assert [entry["url"] for entry in search.snapshot()] == [
        "https://cdn/mkissa.m3u8"
    ]
    assert not search.is_done()

    assert search.wait(3) is True
    assert search.is_done()
    assert sorted(entry["url"] for entry in search.snapshot()) == [
        "https://cdn/animegg.m3u8",
        "https://cdn/mkissa.m3u8",
    ]


def test_a_slow_base_adds_the_providers_it_alone_knows(monkeypatch):
    extractor = _extractor(["https://fast", "https://slow"])

    def request_json(base, path, timeout=20):
        if path.startswith("/episodes/"):
            if base == "https://fast":
                return _episodes("mkissa")
            time.sleep(0.3)
            return _episodes("kaa")
        return _watch(f"https://cdn/{base.rsplit('/', 1)[-1]}.m3u8")

    monkeypatch.setattr(extractor, "_request_json", request_json)

    search = extractor.progressive_search(1, 1).start()
    search.wait(3)

    sources = sorted(entry["source"] for entry in search.snapshot())
    assert sources == ["Anivexa (kaa - S)", "Anivexa (mkissa - S)"]


def test_a_search_without_results_does_not_wait_for_the_timeout(monkeypatch):
    extractor = _extractor(["https://a", "https://b"])
    monkeypatch.setattr(
        extractor,
        "_request_json",
        lambda base, path, timeout=20: {"mkissa": {"error": "boom"}},
    )

    search = extractor.progressive_search(1, 1).start()
    started = time.monotonic()

    assert search.wait_for_first(5) is False
    assert time.monotonic() - started < 2
    assert search.is_done()
    assert search.snapshot() == []


def test_duplicate_urls_across_providers_are_kept_once(monkeypatch):
    extractor = _extractor(["https://a"])

    def request_json(base, path, timeout=20):
        if path.startswith("/episodes/"):
            return {
                "mkissa": _episodes("mkissa")["mkissa"],
                "animegg": _episodes("animegg")["animegg"],
            }
        return _watch("https://cdn/same.m3u8")

    monkeypatch.setattr(extractor, "_request_json", request_json)

    search = extractor.progressive_search(1, 1).start()
    search.wait(3)

    assert len(search.snapshot()) == 1


def test_episodes_are_cached_across_searches(monkeypatch):
    extractor = _extractor(["https://a"])
    episode_calls = []

    def request_json(base, path, timeout=20):
        if path.startswith("/episodes/"):
            episode_calls.append(base)
            return _episodes("mkissa")
        return _watch("https://cdn/x.m3u8")

    monkeypatch.setattr(extractor, "_request_json", request_json)

    extractor.extract_vo(anilist_id=1, episode=1)
    extractor.extract_vo(anilist_id=1, episode=2)

    assert episode_calls == ["https://a"]


def test_ranked_orders_by_priority_while_snapshot_keeps_arrival(monkeypatch):
    extractor = _extractor(["https://a"])

    def request_json(base, path, timeout=20):
        if path.startswith("/episodes/"):
            return {
                "mkissa": _episodes("mkissa")["mkissa"],
                "animegg": _episodes("animegg")["animegg"],
            }
        if "mkissa" in path:
            return _watch("https://cdn/low.m3u8", priority=1)
        return _watch("https://cdn/high.m3u8", priority=9)

    monkeypatch.setattr(extractor, "_request_json", request_json)

    search = extractor.progressive_search(1, 1).start()
    search.wait(3)

    assert len(search.snapshot()) == 2
    assert search.ranked()[0]["url"] == "https://cdn/high.m3u8"


def test_the_deadline_stops_the_long_tail(monkeypatch):
    extractor = _extractor(["https://slow"])
    calls = []

    def request_json(base, path, timeout=20):
        calls.append(path)
        if path.startswith("/episodes/"):
            time.sleep(0.3)
            return _episodes("mkissa")
        return _watch("https://cdn/x.m3u8")

    monkeypatch.setattr(extractor, "_request_json", request_json)

    search = extractor.progressive_search(1, 1, deadline_seconds=0.1).start()

    assert search.wait(3) is True
    assert search.snapshot() == []
    assert [path for path in calls if not path.startswith("/episodes/")] == []
