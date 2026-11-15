"""The source menu marks links but never reorders or hides them.

The search and the link checks finish after the menu is on screen. Rows must
keep their arrival order so the highlighted entry does not move under the
user's arrow keys; the probe verdict is only a suffix on the row.
"""

from autoflix_cli.handlers.goldenanime import (
    _is_direct,
    _probe_failed,
    _probe_marker,
    _probe_reason,
    _stream_menu,
)


def entry(name, url=None, kind="M3U8", **extra):
    return {
        "source": f"Anivexa ({name})",
        "quality": "Auto",
        "type": kind,
        "url": url or f"https://cdn.tld/{name}.m3u8",
        "headers": {},
        **extra,
    }


# --- markers ----------------------------------------------------------------


def test_a_link_without_verdict_has_no_suffix():
    assert _probe_marker(entry("a")) == ""


def test_a_reachable_link_is_ticked():
    assert _probe_marker(entry("a", probe={"ok": True})) == " ✓"


def test_an_unreachable_link_shows_a_short_reason():
    marker = _probe_marker(entry("a", probe={"ok": False, "error": "HTTP 403"}))
    assert marker == " ✗ 403"


def test_probe_reason_condenses_curl_noise():
    noisy = (
        "Timeout: Failed to perform, curl: (28) Operation timed out after "
        "10000 milliseconds with 97304423 out of 334019938 bytes received"
    )
    assert _probe_reason(noisy) == "timeout"
    assert _probe_reason("not a playlist") == "no playlist"
    assert _probe_reason("HTTP 502") == "502"
    assert _probe_reason(None) == "unreachable"


def test_probe_failed_only_when_the_check_answered():
    assert _probe_failed(entry("a")) is False
    assert _probe_failed(entry("a", probe={"ok": True})) is False
    assert _probe_failed(entry("a", probe={"ok": False, "error": "HTTP 403"}))


def test_is_direct_distinguishes_embeds():
    assert _is_direct(entry("a", kind="M3U8"))
    assert _is_direct(entry("a", kind="MP4"))
    assert not _is_direct(entry("a", kind="Player"))


# --- rows -------------------------------------------------------------------


def test_rows_keep_the_arrival_order_when_a_verdict_lands():
    pending = [entry("a"), entry("b"), entry("c")]
    checked = [
        entry("a", probe={"ok": True}),
        entry("b", probe={"ok": False, "error": "HTTP 403"}),
        entry("c"),
    ]

    first = _stream_menu([], pending, waiting=True, pending=2, live_menu=True)
    second = _stream_menu([], checked, waiting=True, pending=1, live_menu=True)

    # Same order, same labels except the verdict suffix: nothing moved.
    assert [row.split(" - ")[0] for row in first.options] == [
        row.split(" - ")[0] for row in second.options
    ]
    assert second.options[0].endswith("✓")
    assert second.options[1].endswith("✗ 403")


def test_a_dead_link_stays_in_the_menu():
    menu = _stream_menu(
        [],
        [entry("a", probe={"ok": False, "error": "HTTP 403"})],
        waiting=False,
        pending=0,
        live_menu=True,
    )
    assert len(menu.entries) == 1
    assert menu.options[0].startswith("Anivexa (a)")


def test_megaplay_comes_first_then_the_search_order():
    menu = _stream_menu(
        [entry("mega", kind="M3U8", url="https://mega.tld/1.m3u8")],
        [entry("a"), entry("b")],
        waiting=False,
        pending=0,
        live_menu=True,
    )
    assert [row.split(" - ")[0] for row in menu.options] == [
        "Anivexa (mega)",
        "Anivexa (a)",
        "Anivexa (b)",
        "← Back",
    ]


def test_duplicate_urls_are_shown_once():
    menu = _stream_menu(
        [entry("mega", url="https://cdn.tld/same.m3u8")],
        [entry("a", url="https://cdn.tld/same.m3u8")],
        waiting=False,
        pending=0,
        live_menu=True,
    )
    assert len(menu.entries) == 1


def test_unsupported_embeds_are_counted_not_listed():
    menu = _stream_menu(
        [],
        [entry("a"), entry("sw", kind="Player", url="https://streamwish.to/e/x")],
        waiting=False,
        pending=0,
        live_menu=True,
    )
    assert [row.split(" - ")[0] for row in menu.options] == [
        "Anivexa (a)",
        "← Back",
    ]
    assert menu.skipped == 1


# --- index map --------------------------------------------------------------


def test_indices_point_at_the_back_and_wait_rows():
    entries = [entry("a"), entry("b")]

    live = _stream_menu([], entries, waiting=True, pending=2, live_menu=True)
    assert live.back == 2
    assert live.wait == -1
    assert live.options[live.back] == "← Back"

    static = _stream_menu([], entries, waiting=True, pending=2, live_menu=False)
    assert static.wait == 2
    assert static.options[static.wait].startswith("⏳ Wait")
    assert static.back == 3
    assert static.options[static.back] == "← Back"


def test_no_wait_row_once_the_search_is_over():
    menu = _stream_menu([], [entry("a")], waiting=False, pending=0, live_menu=False)
    assert menu.wait == -1
    assert menu.options[menu.back] == "← Back"


# --- prompt -----------------------------------------------------------------


def test_prompt_reports_checks_and_dead_links():
    menu = _stream_menu(
        [],
        [
            entry("a", probe={"ok": True}),
            entry("b", probe={"ok": False, "error": "HTTP 403"}),
            entry("c"),
        ],
        waiting=True,
        pending=3,
        live_menu=True,
    )
    assert "3 source(s)" in menu.prompt
    assert "1 checking" in menu.prompt
    assert "1 unreachable" in menu.prompt
    assert "3 still loading" in menu.prompt


def test_prompt_says_searching_before_the_first_source():
    menu = _stream_menu([], [], waiting=True, pending=2, live_menu=True)
    assert "searching" in menu.prompt
    assert menu.options == ["← Back"]
