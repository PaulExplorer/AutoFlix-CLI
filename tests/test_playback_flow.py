"""The auto source entry in the source picker, exercised end to end.

Everything the flow touches outside the module (the extractors, the probe, the
player launch) is stubbed, so these tests assert the wiring: when the entry
appears, what it probes, and what it hands to the player.
"""

import pytest

from autoflix_cli.handlers import playback
from autoflix_cli.scraping import stream_probe as sp
from autoflix_cli.scraping.objects import Episode, Player

UQLOAD = Player("uqload", "https://uqload.vc/embed-1.html")
SIBNET = Player("sibnet", "https://sibnet.ru/embed-abc.html")


def make_source(name, ok=True, kind=sp.KIND_HLS_MASTER, height=1080, url=None):
    return sp.ResolvedSource(
        embed_name=name,
        embed_url=next(p.url for p in (UQLOAD, SIBNET) if p.name == name),
        headers={"Referer": f"https://{name}.example/"},
        player_config={"type": "default"},
        stream_url=url or f"https://cdn.tld/{name}.m3u8",
        ok=ok,
        kind=kind,
        heights=[height] if height else [],
    )


@pytest.fixture(autouse=True)
def no_dev_mode(monkeypatch):
    monkeypatch.setattr(playback.tracker, "get_developer_mode", lambda: False)
    monkeypatch.setattr(playback.tracker, "save_progress", lambda **kw: None)


def run_flow(players, choices, sources=None, headers=None):
    """Drive play_episode_flow with scripted menu answers.

    Returns the list of play_video calls the flow made.
    """
    calls = []
    prompts = []

    def fake_select(options, prompt, default_index=0, **kwargs):
        prompts.append(prompt)
        index = choices.pop(0)
        # A menu answered out of range would silently hide a wiring bug.
        assert 0 <= index < len(options), f"choice {index} out of {options}"
        return index

    def fake_play_video(url, **kwargs):
        calls.append((url, kwargs))
        return True

    def fake_probe(embeds, headers=None, **kwargs):
        calls_probe.append(list(embeds))
        return sources

    calls_probe = []
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(playback, "select_from_list", fake_select)
    monkeypatch.setattr(playback, "play_video", fake_play_video)
    monkeypatch.setattr(playback, "_run_auto_probe", fake_probe)
    try:
        result = playback.play_episode_flow(
            provider_name="Test",
            series_title="Series",
            season_title="S1",
            episode=Episode("Episode 1", players),
            series_url="https://series",
            season_url="https://season",
            headers=headers or {"Referer": "https://provider.example/"},
        )
    finally:
        monkeypatch.undo()

    assert result is True
    return calls, calls_probe, prompts


# --- menu entries -----------------------------------------------------------


def test_auto_entry_absent_with_a_single_source():
    calls, _, _ = run_flow([UQLOAD], [0])
    assert len(calls) == 1
    assert calls[0][1]["resolved"] is None


def test_auto_entry_present_with_several_sources():
    _, _, prompts = run_flow([UQLOAD, SIBNET], [1, 0])
    assert any("Select Player" in p for p in prompts)


def test_back_from_source_list_returns_nothing(monkeypatch):
    monkeypatch.setattr(playback.tracker, "get_developer_mode", lambda: False)
    monkeypatch.setattr(
        playback, "select_from_list", lambda options, prompt, **kw: len(options) - 1
    )
    monkeypatch.setattr(playback, "play_video", lambda url, **kw: True)

    result = playback.play_episode_flow(
        provider_name="Test",
        series_title="Series",
        season_title="S1",
        episode=Episode("Episode 1", [UQLOAD, SIBNET]),
        series_url="",
        season_url="",
        headers={},
    )
    assert result is False


# --- auto flow --------------------------------------------------------------


def test_auto_probes_every_supported_source():
    sources = [make_source("uqload"), make_source("sibnet")]
    # choice 0 = Auto, choice 1 = the ranked menu's second entry
    _, probed, _ = run_flow([UQLOAD, SIBNET], [0, 1], sources)
    assert len(probed) == 1
    assert probed[0] == [UQLOAD, SIBNET]


def test_auto_launches_the_source_the_user_picked():
    best = make_source("uqload", height=1080)
    other = make_source("sibnet", height=720)
    calls, _, _ = run_flow([UQLOAD, SIBNET], [0, 1], [best, other])

    url, kwargs = calls[0]
    assert kwargs["resolved"] is other
    assert url == SIBNET.url
    # The headers of the embed that produced the link, not the episode ones.
    assert kwargs["headers"] == {"Referer": "https://sibnet.example/"}


def test_auto_keeps_the_config_of_the_chosen_embed():
    source = make_source("uqload")
    source.player_config = {"type": "uqload", "ext": "mp4"}
    calls, _, _ = run_flow([UQLOAD, SIBNET], [0, 0], [source])
    assert calls[0][1]["resolved"].player_config["type"] == "uqload"


def test_back_from_ranked_menu_returns_to_source_list():
    sources = [make_source("uqload"), make_source("sibnet")]
    # 0 = Auto, 2 = "← Back to source list", 2 = sibnet in the source list
    calls, _, _ = run_flow([UQLOAD, SIBNET], [0, 2, 2], sources)
    assert calls[0][1]["resolved"] is None
    assert calls[0][0] == SIBNET.url


def test_stale_source_is_resolved_again(monkeypatch):
    stale = make_source("uqload")
    stale.probed_at = 0.0  # anything older than STALE_AFTER
    refreshed = make_source("uqload", height=720)

    monkeypatch.setattr(
        playback.stream_probe, "resolve_source", lambda *a, **kw: refreshed
    )
    calls, _, _ = run_flow([UQLOAD, SIBNET], [0, 0], [stale])
    assert calls[0][1]["resolved"] is refreshed


def test_source_that_stopped_resolving_still_gets_a_chance(monkeypatch):
    # The re-extract failed, but a transient extraction block must not cancel
    # a link the player may still be able to play.
    stale = make_source("uqload")
    stale.probed_at = 0.0
    dead = make_source("uqload", ok=False, height=0)
    monkeypatch.setattr(
        playback.stream_probe, "resolve_source", lambda *a, **kw: dead
    )
    calls, _, _ = run_flow([UQLOAD, SIBNET], [0, 0], [stale])
    assert calls[0][0] == UQLOAD.url
    assert calls[0][1]["resolved"] is stale

# --- source naming ----------------------------------------------------------


def test_numbered_sources_are_labelled_by_their_embed():
    generic = [
        Player("Lecteur 1", "https://embed4me.net/embed-abc.html"),
        Player("Lecteur 2", "https://ansembed.net/embed-def.html"),
        Player("Lecteur 3", "https://minochinos.net/embed-ghi.html"),
        Player("Lecteur 4", "https://sibnet.ru/embed-jkl.html"),
    ]
    assert playback._source_labels(generic) == [
        "embed4me",
        "ansembed",
        "minochinos",
        "sibnet",
    ]


def test_duplicate_embed_names_are_told_apart_by_url():
    duplicated = [
        Player("Lecteur 1", "https://embed4me.net/embed-a.html"),
        Player("Lecteur 2", "https://embed4me.net/embed-b.html"),
    ]
    assert playback._source_labels(duplicated) == [
        "embed4me (embed4me.net/embed-a)",
        "embed4me (embed4me.net/embed-b)",
    ]

