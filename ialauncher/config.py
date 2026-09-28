"""Paths and environment settings (read once at startup)."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOME = Path.home()

LISTEN_HOST = os.environ.get("IA_LAUNCHER_HOST", "0.0.0.0")
LISTEN_PORT = int(os.environ.get("IA_LAUNCHER_PORT", "8090"))

MODELS_DIR = Path(os.environ.get("IA_LAUNCHER_MODELS_DIR", HOME / "ia_models"))
LOG_DIR = ROOT / "logs"

ENGINES_FILE = ROOT / "engines.json"
MODELS_FILE = ROOT / "models.json"
SETTINGS_FILE = ROOT / "settings.json"
LOCALES_DIR = ROOT / "locales"
CATALOG_DIR = ROOT / "catalog"
INDEX_HTML = ROOT / "index.html"

POLL_S = 2.0
# VRAM used by the display (Windows) and WSL with no model loaded; replaced by the real value
# as soon as the GPU is seen with no compute process
DEFAULT_BASELINE_MIB = 1500
