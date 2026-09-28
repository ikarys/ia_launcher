"""Paths and environment settings (read once at startup)."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOME = Path.home()

LISTEN_HOST = os.environ.get("IA_LAUNCHER_HOST", "0.0.0.0")
LISTEN_PORT = int(os.environ.get("IA_LAUNCHER_PORT", "8090"))

DEFAULT_MODELS_DIR = os.environ.get("IA_LAUNCHER_MODELS_DIR", "~/ia_models")  # changed in Settings
LOG_DIR = ROOT / "logs"

# engines.json, models.json, settings.json: local, never versioned
CONFIG_DIR = Path(os.environ.get("IA_LAUNCHER_CONFIG_DIR", ROOT)).expanduser()
ENGINES_FILE = CONFIG_DIR / "engines.json"
MODELS_FILE = CONFIG_DIR / "models.json"
SETTINGS_FILE = CONFIG_DIR / "settings.json"
LOCALES_DIR = ROOT / "locales"
CATALOG_DIR = ROOT / "catalog"
WEB_DIR = ROOT / "web"  # the page: index.html, css/, js/

POLL_S = 2.0
# VRAM used by the display (Windows) and WSL with no model loaded; replaced by the real value
# as soon as the GPU is seen with no compute process
DEFAULT_BASELINE_MIB = 1500
