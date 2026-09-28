"""Is an engine installed? Its files on disk."""
import shutil
from pathlib import Path

from ..domain.engine import expand


def is_installed(e):
    """Executable present, and the script given as first argument (bash /path/start.sh), and the
    built binary of its clone when it declares one."""
    command = e["command"]
    exe = expand(command[0])
    arg = expand(command[1]) if len(command) > 1 and isinstance(command[1], str) else ""
    ok = Path(exe).exists() if "/" in exe else shutil.which(exe)
    ok = ok and (not arg.startswith("/") or "{" in arg or Path(arg).exists())
    return bool(ok) and (not e.get("binary") or (Path(expand(e["repo"])) / e["binary"]).exists())
