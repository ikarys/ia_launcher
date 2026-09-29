"""Models (models.json): validation and the resolved form the page and the supervisor use.

A model = engine + file + port + params + profiles. A param value is "x" (fixed) or
["x", "y"] / [["x", "label"], ...] (a menu on the model card, the first one by default).
"""
import re
from pathlib import Path

from ..errors import LaunchError
from ..i18n import loc, tr

WORD = re.compile(r"\w+")
VALUE = re.compile(r"[\w.:/+-]{1,200}")
EXTRA_ARG = re.compile(r"[\w.:/+=,@-]{1,300}")


def choices_of(v):
    vals = v if isinstance(v, list) else [v]
    return [c if isinstance(c, list) else [str(c), str(c)] for c in vals]


def labelled(spec, v):
    """Menu choices of a card; the engine's labels for values given without one."""
    names = dict(spec.get("values", []))
    return [[x, names.get(x, lbl) if lbl == x else lbl] for x, lbl in choices_of(v)]


def vram_estimate(size_bytes):
    # ponytail: weights +10 % + 1 GB (KV cache at a medium context, runtime);
    # set vram_mib in models.json if a large context overflows
    return round(size_bytes / 2**20 * 1.1 + 1024)


def validate(mid, c, engines, *, listen_port, file_exists=lambda p: Path(p).is_file()):
    """Raise LaunchError on the first problem of a models.json entry (the page writes it:
    this is a trust boundary)."""
    def need(cond, msg_key, /, **kw):
        if not cond:
            raise LaunchError(tr("cfg.model_prefix", id=mid, msg=tr(msg_key, **kw)))
    need(WORD.fullmatch(mid), "cfg.model_id")
    e = engines.get(c.get("engine"))
    need(e, "cfg.unknown_engine", engines=", ".join(engines))
    need(WORD.fullmatch(str(c.get("kind", ""))), "cfg.kind")
    need(isinstance(c.get("name"), str) and c["name"].strip(), "cfg.name_missing")
    need(isinstance(c.get("port"), int) and 1024 <= c["port"] <= 65535 and c["port"] != listen_port, "cfg.port")
    need(re.fullmatch(r"[\w-]*", str(c.get("task", ""))), "cfg.task")
    need(isinstance(c.get("vram_mib", 0), int) and c.get("vram_mib", 0) >= 0, "cfg.vram")
    if e["needs_file"]:
        need(isinstance(c.get("file"), str) and file_exists(c["file"]), "cfg.file_missing", file=c.get("file"))
        need(Path(c["file"]).suffix in e["file_ext"], "cfg.file_ext", engine=loc(e["label"]),
             exts=" / ".join(e["file_ext"]))
    extra = c.get("extra_args", [])
    need(isinstance(extra, list) and all(isinstance(a, str) and EXTRA_ARG.fullmatch(a) for a in extra),
         "cfg.extra_args")
    for k, v in c.get("params", {}).items():
        need(k in e["params"], "cfg.unknown_param", engine=c["engine"], key=k, params=", ".join(e["params"]))
        allowed = [x for x, _label in e["params"][k].get("values", [])]
        for val, _label in choices_of(v):
            need(VALUE.fullmatch(str(val)), "cfg.bad_value", key=k, value=repr(val))
            need(not allowed or val in allowed, "cfg.value_not_allowed", key=k, value=repr(val),
                 allowed=", ".join(allowed))
    for name, prof in c.get("profiles", {}).items():
        for k, v in prof.items():
            need(v in [x for x, _label in choices_of(c.get("params", {}).get(k, []))], "cfg.profile_value",
                 name=name, key=k, value=v)


def resolve(mid, c, e, *, vram_mib):
    """models.json entry + its engine -> what the supervisor and the page use."""
    params = c.get("params", {})
    return {
        "kind": c["kind"], "name": c["name"], "desc": c.get("desc", ""), "task": c.get("task"),
        "engine": e["label"], "engine_id": c["engine"],
        "port": c["port"], "health": e["health"], "endpoint": e["endpoint"],
        "procs": e["procs"], "match": c.get("file") if e.get("match_file") else None,
        "conflicts": {int(k): v for k, v in c.get("conflicts", {}).items()},
        "repo": e.get("repo"), "build": e.get("build"), "binary": e.get("binary"),
        "fixed": {k: str(v) for k, v in params.items() if not isinstance(v, list)},
        "vram_mib": vram_mib,
        "options": [{"key": k, "label": e["params"][k]["label"], "choices": labelled(e["params"][k], v),
                     "default": choices_of(v)[0][0]}
                    for k, v in params.items() if isinstance(v, list)],
        "profiles": c.get("profiles", {}),
        "config": c,
    }


def clean_options(model, opts):
    """Options sent by the page -> only known keys and values (else the default)."""
    clean = {}
    for o in model["options"]:
        v = str(opts.get(o["key"], o["default"]))
        clean[o["key"]] = v if v in [c[0] for c in o["choices"]] else o["default"]
    return clean
