"""MegaPlay answers from an AniList id, so only its own payload needs parsing.

The player returns ``<title>File 13461 - MegaPlay</title>`` on success, an
encrypted blob for the sources, and caption tracks in the same payload.
"""

from autoflix_cli.scraping.megaplay import MegaPlayExtractor


def test_content_id_is_read_from_the_player_title(monkeypatch):
    extractor = MegaPlayExtractor()
    monkeypatch.setattr(
        extractor,
        "_get_text",
        lambda url, params=None: "<title>File 13461 - MegaPlay</title>",
    )

    assert extractor.content_id(154587, 1) == "13461"


def test_content_id_is_none_on_the_error_page(monkeypatch):
    extractor = MegaPlayExtractor()
    monkeypatch.setattr(
        extractor, "_get_text", lambda url, params=None: "<title>Error - MegaPlay</title>"
    )

    assert extractor.content_id(154587, 1) is None


def test_streams_build_a_manifest_with_caption_tracks(monkeypatch):
    extractor = MegaPlayExtractor()
    monkeypatch.setattr(extractor, "content_id", lambda *a, **k: "13461")
    monkeypatch.setattr(
        extractor,
        "sources",
        lambda content_id: {
            "enc": "encrypted",
            "tracks": [
                {
                    "file": "https://cdn.example/fr.vtt",
                    "label": "French",
                    "kind": "captions",
                },
                {
                    "file": "https://cdn.example/thumb.jpg",
                    "label": "Thumbnail",
                    "kind": "thumbnails",
                },
            ],
        },
    )
    monkeypatch.setattr(
        extractor,
        "_decrypt",
        lambda text: {"file": "https://cdn.example/master.m3u8?token=abc"},
    )

    results = extractor.streams(154587, 1)

    assert len(results) == 1
    entry = results[0]
    assert entry["source"] == "MegaPlay (sub)"
    assert entry["type"] == "M3U8"
    assert entry["url"] == "https://cdn.example/master.m3u8?token=abc"
    assert entry["language"] == "sub"
    assert [track["lang"] for track in entry["subtitles"]] == ["French"]
    assert entry["subtitles"][0]["headers"]["Referer"] == "https://megaplay.buzz/"


def test_streams_stop_when_the_payload_cannot_be_decrypted(monkeypatch):
    extractor = MegaPlayExtractor()
    monkeypatch.setattr(extractor, "content_id", lambda *a, **k: "13461")
    monkeypatch.setattr(extractor, "sources", lambda content_id: {"enc": "encrypted"})
    monkeypatch.setattr(extractor, "_decrypt", lambda text: None)

    assert extractor.streams(154587, 1) == []


def test_streams_without_content_id_skip_the_network(monkeypatch):
    extractor = MegaPlayExtractor()
    monkeypatch.setattr(extractor, "content_id", lambda *a, **k: None)

    def boom(*args, **kwargs):
        raise AssertionError("sources should not be requested")

    monkeypatch.setattr(extractor, "sources", boom)

    assert extractor.streams(154587, 1) == []


def test_unknown_audio_falls_back_to_sub(monkeypatch):
    extractor = MegaPlayExtractor()
    seen = {}

    def content_id(anilist_id, episode, audio):
        seen["audio"] = audio
        return None

    monkeypatch.setattr(extractor, "content_id", content_id)

    extractor.streams(154587, 1, audio="vf")

    assert seen["audio"] == "sub"
