import os

from ..config_loader import load_local_jsonc, load_remote_jsonc
from ..defaults import DEFAULT_SOURCE_PORTAL

# Paths
REMOTE_CONFIG_URL = "https://raw.githubusercontent.com/PaulExplorer/AutoFlix-CLI/refs/heads/main/data/source_portal.jsonc"
# src/autoflix_cli/scraping/config.py -> ../../../data/source_portal.jsonc
LOCAL_CONFIG_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "data", "source_portal.jsonc"
)

# Load Portals (Remote with fallback to DEFAULT, then override with Local if exists)
portals = load_remote_jsonc(REMOTE_CONFIG_URL, DEFAULT_SOURCE_PORTAL)
local_portals = load_local_jsonc(LOCAL_CONFIG_PATH)

if local_portals:
    portals.update(local_portals)
