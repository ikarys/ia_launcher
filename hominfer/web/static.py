"""The page's assets (web/css, web/js...). The views themselves are rendered by page.py."""
from .. import config

TYPES = {".css": "text/css; charset=utf-8", ".js": "text/javascript; charset=utf-8",
         ".svg": "image/svg+xml", ".png": "image/png"}


def find(url_path):
    """URL path -> (bytes, content type), or None. Never serves anything outside web/."""
    root = config.WEB_DIR.resolve()
    f = (root / url_path.lstrip("/")).resolve()
    if not f.is_relative_to(root) or not f.is_file() or f.suffix not in TYPES:
        return None
    return f.read_bytes(), TYPES[f.suffix]
