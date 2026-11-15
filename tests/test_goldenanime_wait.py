"""The "wait for the remaining sources" entry must not trap the user.

Sources keep arriving in the background while the menu is open; the explicit
entry only blocks long enough to see them land, and reports progress so a slow
instance does not look like a freeze.
"""

from autoflix_cli.handlers import goldenanime as g


class FakeSearch:
    """Minimal ProgressiveSearch stand-in driven by ``wait`` calls."""

    def __init__(self, counts, done_after, pending=2):
        self._counts = counts
        self._done_after = done_after
        self._pending = pending
        self.waits = 0

    def is_done(self):
        return self.waits >= self._done_after

    def wait(self, timeout=None):
        self.waits += 1
        return self.is_done()

    def snapshot(self):
        index = min(self.waits, len(self._counts) - 1)
        return [None] * self._counts[index]

    def pending(self):
        return 0 if self.is_done() else self._pending


def test_it_reports_the_sources_that_arrive(monkeypatch):
    lines = []
    monkeypatch.setattr(g, "print_info", lines.append)

    g._wait_for_remaining(FakeSearch(counts=[1, 2, 4], done_after=2))

    assert any("2 source(s) so far" in line for line in lines)
    assert lines[-1] == "Search finished: 4 source(s)."


def test_a_slow_search_returns_to_the_menu(monkeypatch):
    lines = []
    monkeypatch.setattr(g, "print_info", lines.append)

    g._wait_for_remaining(FakeSearch(counts=[3], done_after=10**9), timeout=0.02)

    assert lines[-1] == "Still searching: 3 source(s), 2 still loading."
