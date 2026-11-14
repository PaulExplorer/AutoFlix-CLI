"""Anivexa ``/watch`` payloads do not share a shape between providers.

mkissa answers with ``sources`` (``extractedUrl``/``extractedType``/headers),
animegg with ``streams`` (``url``/``type``). Both must produce the same entry
structure, ordered by the provider-declared priority.
"""

from autoflix_cli.scraping.goldenanime import AnimeExtractor


def _extractor(monkeypatch, provider, episode_id, watch_payload):
    extractor = AnimeExtractor()
    monkeypatch.setattr(
        extractor,
        "get_episodes",
        lambda aid: {
            provider: {
                "meta": {},
                "episodes": {"sub": [{"number": 1, "id": episode_id}]},
            }
        },
    )
    monkeypatch.setattr(extractor, "_get_json", lambda path, timeout=20: watch_payload)
    return extractor


MKISSA_WATCH = {
    "anilistId": 154587,
    "mkissaId": "ReHMC7TQnch3C6z8j",
    "episode": 1,
    "audio": "sub",
    "sources": [
        {
            "name": "Yt-mp4",
            "url": "https://streamwish.to/e/26qc49bl6muh",
            "extractedUrl": (
                "https://tools.fast4speed.rsvp/media9/videos/abc/sub/1"
                "?Authorization=token"
            ),
            "extractedType": "direct",
            "type": "player",
            "priority": 7.9,
            "headers": {
                "Referer": "https://mkissa.to",
                "User-Agent": "Mozilla/5.0",
            },
        },
        {
            "name": "Sw",
            "url": "https://streamwish.to/e/26qc49bl6muh",
            "extractedUrl": None,
            "extractedType": None,
            "type": "iframe",
            "priority": 5.5,
            "headers": {"Referer": "https://mkissa.to"},
        },
    ],
}

ANIMEGG_WATCH = {
    "anilistId": 154587,
    "episode": 1,
    "providerEpisode": 1,
    "audio": "sub",
    "streams": [
        {
            "url": "https://www.animegg.org/play/445674/video.mp4?for=101794676082129",
            "type": "mp4",
            "priority": 1,
        },
        {
            "url": "https://www.animegg.org/embed/131519",
            "type": "embed",
            "priority": 1,
        },
    ],
}


def test_mkissa_sources_are_read_and_ranked_by_priority(monkeypatch):
    extractor = _extractor(
        monkeypatch,
        "mkissa",
        "watch/mkissa/154587/sub/mkissa-1",
        MKISSA_WATCH,
    )

    results = extractor.extract_vo(anilist_id=154587, episode=1)

    assert [r["type"] for r in results] == ["MP4", "Player"]
    assert results[0]["url"].startswith("https://tools.fast4speed.rsvp/")
    assert results[0]["headers"]["Referer"] == "https://mkissa.to"
    assert results[0]["source"] == "Anivexa (mkissa - Yt-mp4)"
    assert results[1]["url"] == "https://streamwish.to/e/26qc49bl6muh"


def test_animegg_streams_get_a_referer_from_the_payload_host(monkeypatch):
    extractor = _extractor(
        monkeypatch,
        "animegg",
        "watch/animegg/154587/sub/animegg-1",
        ANIMEGG_WATCH,
    )

    results = extractor.extract_vo(anilist_id=154587, episode=1)

    assert [r["type"] for r in results] == ["MP4", "Player"]
    assert results[0]["headers"]["Referer"] == "https://www.animegg.org/"


def test_payload_level_subtitles_are_attached_to_every_stream(monkeypatch):
    payload = {
        "streams": [
            {"url": "https://cdn.example/video.mp4", "type": "mp4", "priority": 1}
        ],
        "subtitles": [
            {"url": "https://cdn.example/fr.vtt", "srclang": "fr", "label": "French"}
        ],
    }
    extractor = _extractor(
        monkeypatch,
        "anikoto",
        "watch/anikoto/154587/sub/anikoto-1",
        payload,
    )

    results = extractor.extract_vo(anilist_id=154587, episode=1)

    assert results[0]["subtitles"][0]["lang"] == "fr"
    assert results[0]["subtitles"][0]["headers"]["Referer"] == "https://cdn.example/"


def test_host_referer_is_none_without_a_scheme():
    assert AnimeExtractor._host_referer("not-a-url") is None
    assert AnimeExtractor._host_referer("https://cdn.tld/a.mp4") == "https://cdn.tld/"
