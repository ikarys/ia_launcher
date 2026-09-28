"""The page's static files (web/): the HTML shell for every view, and its CSS / JS."""
from .. import config

TYPES = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
         ".js": "text/javascript; charset=utf-8", ".svg": "image/svg+xml", ".png": "image/png"}
VIEWS = ("/", "/index.html", "/modeles")  # one page; /modeles = the model management view


def find(url_path):
    """URL path -> (bytes, content type), or None. Never serves anything outside web/."""
    if url_path in VIEWS:
        url_path = "/index.html"
    root = config.WEB_DIR.resolve()
    f = (root / url_path.lstrip("/")).resolve()
    if not f.is_relative_to(root) or not f.is_file() or f.suffix not in TYPES:
        return None
    return f.read_bytes(), TYPES[f.suffix]
