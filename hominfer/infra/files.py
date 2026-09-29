"""Files: atomic writes, hand-readable JSON, log tails, sizes."""
import json
import os
import re

ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]|\r")


def read_json(path, default):
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        return default


def write_atomic(path, text):
    tmp = path.with_suffix(".tmp")
    tmp.write_text(text)
    os.replace(tmp, path)


def compact_json(v, ind=0, lead=0, width=110):
    """JSON as written by hand: a value on one line when it fits, else one entry per line
    (plain values fill each line up to the width)."""
    one = json.dumps(v, ensure_ascii=False)
    if not isinstance(v, (dict, list)) or not v or ind + lead + len(one) <= width:
        return one
    pad = " " * (ind + 2)
    end = "\n" + " " * ind
    if isinstance(v, dict):
        rows = [f"{pad}{json.dumps(k, ensure_ascii=False)}: {compact_json(x, ind + 2, len(k) + 4, width)}"
                for k, x in v.items()]
        return "{\n" + ",\n".join(rows) + end + "}"
    if all(not isinstance(x, (dict, list)) for x in v):
        lines, cur = [], ""
        for x in (json.dumps(x, ensure_ascii=False) for x in v):
            if cur and ind + 2 + len(cur) + len(x) + 2 > width:
                lines.append(cur)
                cur = ""
            cur += (", " if cur else "") + x
        return "[\n" + ",\n".join(pad + line for line in lines + [cur]) + end + "]"
    return "[\n" + ",\n".join(pad + compact_json(x, ind + 2, 0, width) for x in v) + end + "]"


def tail(path, lines=150):
    """Last lines of a log, without terminal escape codes."""
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - 128 * 1024))
            text = f.read().decode("utf-8", "replace")
    except FileNotFoundError:
        return ""
    return "\n".join(ANSI.sub("", text).splitlines()[-lines:])


def size_of(path):
    if path.is_file():
        return path.stat().st_size
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file() and not f.is_symlink())
