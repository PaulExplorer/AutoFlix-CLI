import logging
import os

log = logging.getLogger("autoflix")


def setup_logging() -> None:
    """Configure internal diagnostics (stderr, WARNING by default).

    Set ``AUTOFIX_LOG=DEBUG`` (or INFO) to see internal messages
    such as upstream fetch failures or proxy requests.
    """
    level_name = os.environ.get("AUTOFIX_LOG", "WARNING").upper()
    level = getattr(logging, level_name, logging.WARNING)
    logging.basicConfig(
        level=level,
        format="%(levelname)s: %(message)s",
    )


def apply_developer_logging(enabled: bool) -> None:
    """Apply developer-mode log verbosity at runtime.

    When enabled, force DEBUG on the root and ``autoflix`` loggers so
    proxy retries and scraper failures become visible. When disabled,
    restore the level from ``AUTOFIX_LOG`` (WARNING by default).
    """
    if enabled:
        level = logging.DEBUG
    else:
        level_name = os.environ.get("AUTOFIX_LOG", "WARNING").upper()
        level = getattr(logging, level_name, logging.WARNING)
    logging.getLogger().setLevel(level)
    logging.getLogger("autoflix").setLevel(level)
