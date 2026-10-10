"""The auto source entry in the source picker, exercised end to end.

Everything the flow touches outside the module (the extractors, the probe, the
player launch) is stubbed, so these tests assert the wiring: when the entry
appears, what it probes, and what it hands to the player.
"""

import time

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
        # Freshly probed, so the flow does not re-resolve it for real. Tests
        # about staleness set this back to 0 explicitly.
        probed_at=time.monotonic(),
    )


@pytest.fixture(autouse=True)
def no_dev_mode(monkeypatch):
    monkeypatch.setattr(playback.tracker, "get_developer_mode", lambda: False)
    monkeypatch.setattr(playback.tracker, "save_progress", lambda **kw: None)
    # Default off; the auto-source tests opt in explicitly.
    monkeypatch.setattr(playback.tracker, "get_auto_source", lambda: False)


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
    stale.probed_at = time.monotonic() - sp.STALE_AFTER - 1
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
    stale.probed_at = time.monotonic() - sp.STALE_AFTER - 1
    dead = make_source("uqload", ok=False, height=0)
    monkeypatch.setattr(
        playback.stream_probe, "resolve_source", lambda *a, **kw: dead
    )
    calls, _, _ = run_flow([UQLOAD, SIBNET], [0, 0], [stale])
    assert calls[0][0] == UQLOAD.url
    assert calls[0][1]["resolved"] is stale

# --- auto-pick setting ------------------------------------------------------


def run_with_auto_setting(monkeypatch, enabled, players, sources, choices):
    """Drive play_episode_flow with the auto-source setting on or off."""
    calls, menus = [], []
    monkeypatch.setattr(playback.tracker, "get_developer_mode", lambda: False)
    monkeypatch.setattr(playback.tracker, "save_progress", lambda **kw: None)
    monkeypatch.setattr(playback.tracker, "get_auto_source", lambda: enabled)
    monkeypatch.setattr(playback, "_run_auto_probe", lambda p, h: list(sources))
    monkeypatch.setattr(
        playback,
        "select_from_list",
        lambda options, prompt, **kw: menus.append((prompt, options))
        or choices.pop(0),
    )
    monkeypatch.setattr(
        playback, "play_video", lambda url, **kw: calls.append((url, kw)) or True
    )
    result = playback.play_episode_flow(
        provider_name="Test",
        series_title="S",
        season_title="S1",
        episode=Episode("E1", players),
        series_url="",
        season_url="",
        headers={"Referer": "https://p/"},
    )
    return result, calls, menus


def test_auto_pick_plays_the_best_source_without_a_menu(monkeypatch):
    best = make_source("uqload", height=1080)
    other = make_source("sibnet", height=720)
    result, calls, menus = run_with_auto_setting(
        monkeypatch, True, [UQLOAD, SIBNET], [best, other], []
    )
    assert result is True
    assert menus == [], "the source menu must not appear"
    assert calls[0][1]["resolved"] is best


def test_auto_pick_off_shows_the_source_menu(monkeypatch):
    result, calls, menus = run_with_auto_setting(
        monkeypatch, False, [UQLOAD, SIBNET], [make_source("uqload")], [1]
    )
    assert menus[0][0] == "\U0001f3ae Select Player:"
    assert calls[0][1]["resolved"] is None


def test_auto_pick_falls_back_to_the_menu_when_nothing_works(monkeypatch):
    dead = [make_source("uqload", ok=False), make_source("sibnet", ok=False)]
    result, calls, menus = run_with_auto_setting(
        monkeypatch, True, [UQLOAD, SIBNET], dead, [1]
    )
    assert menus[0][0] == "\U0001f3ae Select Player:"
    assert calls[0][1]["resolved"] is None


def test_auto_pick_is_skipped_with_a_single_source(monkeypatch):
    # One source is nothing to rank, so the plain menu stays.
    result, calls, menus = run_with_auto_setting(
        monkeypatch, True, [UQLOAD], [make_source("uqload")], [0]
    )
    assert menus[0][0] == "\U0001f3ae Select Player:"
    assert calls[0][1]["resolved"] is None


def test_pick_best_source_skips_the_sources_already_tried(monkeypatch):
    # A retry after a failed playback must move to the next source.
    first = make_source("uqload", height=1080)
    second = make_source("sibnet", height=720)
    monkeypatch.setattr(
        playback, "_probe_and_report", lambda players, headers: ([first, second], [])
    )
    assert playback._pick_best_source([UQLOAD, SIBNET], {}) is first
    assert (
        playback._pick_best_source([UQLOAD, SIBNET], {}, exclude={first.embed_url})
        is second
    )


def test_pick_best_source_returns_none_when_all_were_tried(monkeypatch):
    only = make_source("uqload")
    monkeypatch.setattr(
        playback, "_probe_and_report", lambda players, headers: ([only], [])
    )
    assert (
        playback._pick_best_source([UQLOAD], {}, exclude={only.embed_url}) is None
    )
