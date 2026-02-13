from ..config_loader import load_remote_jsonc
from ..defaults import DEFAULT_SOURCE_PORTAL

# Scraper Portals
portals = load_remote_jsonc(
    "https://raw.githubusercontent.com/PaulExplorer/AutoFlix-CLI/refs/heads/main/data/source_portal.jsonc",
    DEFAULT_SOURCE_PORTAL,
)
