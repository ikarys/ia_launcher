"""Folder browser for the page (to pick the models folder): folder names only, never files."""
from pathlib import Path

from ..errors import LaunchError
from ..i18n import tr

MAX_ENTRIES = 500
WINDOWS_DRIVES = Path("/mnt")  # WSL mounts the Windows drives there (/mnt/c, /mnt/d...)


def shortcuts():
    """Where to start browsing: home, the Windows drives under WSL, the root."""
    drives = sorted(d for d in WINDOWS_DRIVES.glob("?") if d.is_dir()) if WINDOWS_DRIVES.is_dir() else []
    return [str(Path.home()), *map(str, drives), "/"]


def browse(text):
    """'~/ia_models' -> {path, parent, dirs, shortcuts}; the folder has to exist."""
    p = Path(str(text or "~").strip() or "~").expanduser()
    if not p.is_absolute() or not p.is_dir():
        raise LaunchError(tr("folders.not_a_folder", path=text))
    try:
        dirs = sorted((d.name for d in p.iterdir() if not d.name.startswith(".") and d.is_dir()), key=str.lower)
    except PermissionError:
        raise LaunchError(tr("folders.denied", path=p))
    return {"path": str(p), "parent": str(p.parent) if p.parent != p else None,
            "dirs": dirs[:MAX_ENTRIES], "shortcuts": shortcuts()}
