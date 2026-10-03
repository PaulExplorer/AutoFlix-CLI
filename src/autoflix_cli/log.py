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
