import pytest

from autoflix_cli.tracker import tracker


@pytest.fixture(autouse=True)
def isolated_settings(tmp_path, monkeypatch):
    """Keep the suite away from the developer's real settings file.

    ``autoflix_cli.tracker.tracker`` is a module-level singleton that reads
    and writes ``~/.local/share/AutoFlixCLI/progress.json``. Without this, a
    test that touches it inherits the developer's own preferences (language,
    chosen player, auto-source...) and can rewrite their watch history.
    """
    monkeypatch.setattr(tracker, "data", {})
    monkeypatch.setattr(tracker, "data_file", tmp_path / "progress.json")
    monkeypatch.setattr(tracker, "_save_data", lambda: None)