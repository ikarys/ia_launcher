"""Inference engines (engines.json): validation and command building.

An engine = how to run one kind of model: command, env, health check, params. Engines are
declared by hand (never by the page): the page picks an engine for a model, never a command.
Placeholders in command / env: {port} {file} {file_name} {file_dir} {models_dir} {model_id}
and every param ({ctx}...). Optional param: an env var or argument that ends up empty is
dropped, and so is a group of arguments (a list inside command) with any empty placeholder.
"""
import re
from pathlib import Path

from ..errors import LaunchError
from ..i18n import tr

PLACEHOLDER = re.compile(r"\{(\w+)\}")
BUILTIN_VARS = {"port", "file", "file_name", "file_dir", "models_dir", "model_id"}
WORD = re.compile(r"\w+")
# a model uses its "auto" device on GPU only if this much VRAM stays free on top of its own
AUTO_DEVICE_MARGIN_MIB = 1536


def expand(s):
    """'~/x' -> '/home/me/x' (only a leading ~/, as in the JSON files)."""
    return str(Path.home() / s[2:]) if isinstance(s, str) and s.startswith("~/") else s


def flat(command):
    return [x for a in command for x in (a if isinstance(a, list) else [a])]


def validate(eid, e):
    """Raise LaunchError on the first problem of a raw engines.json entry."""
    def need(cond, msg_key, /, **kw):
        if not cond:
            raise LaunchError(tr("cfg.engines_prefix", id=eid, msg=tr(msg_key, **kw)))
    need(re.fullmatch(r"[\w.-]+", eid), "cfg.engine_id")
    need(isinstance(e.get("label"), (str, dict)) and e["label"], "cfg.label_missing")
    command = e.get("command")
    need(isinstance(command, list) and command and isinstance(command[0], str)
         and all(isinstance(a, str) or isinstance(a, list) and all(isinstance(x, str) for x in a) for a in command),
         "cfg.command")
    env = e.get("env", {})
    need(isinstance(env, dict) and all(isinstance(v, str) for v in env.values()), "cfg.env")
    need(isinstance(e.get("procs"), list) and e["procs"], "cfg.procs")
    for k in ("health", "endpoint"):
        need(str(e.get(k, "")).startswith("/"), "cfg.http_path", key=k)
    params = e.get("params", {})
    need(isinstance(params, dict) and all(WORD.fullmatch(k) for k in params), "cfg.params_keys")
    need(e.get("device_param") in (None, *params), "cfg.device_param")
    for arg in [*flat(command), *env.values()]:
        for var in PLACEHOLDER.findall(arg):
            need(var in BUILTIN_VARS or var in params, "cfg.placeholder", var="{" + var + "}",
                 builtins=", ".join(sorted(BUILTIN_VARS)))


def normalize(e):
    """Validated raw entry -> the form the launcher uses (params as dicts, derived fields)."""
    e = dict(e)
    e["params"] = {k: v if isinstance(v, dict) else {"label": v} for k, v in e.get("params", {}).items()}
    e["file_ext"] = e.get("file_ext", [])
    e["needs_file"] = bool(e["file_ext"])
    if e.get("repo"):
        e["repo"] = expand(e["repo"])
    return e


def build_command(e, mid, model, params, *, vram_need, free_vram, models_dir):
    """Engine + models.json entry + chosen params -> (argv, env, VRAM to reserve).

    vram_need: VRAM the model needs on GPU; free_vram: VRAM free now (for device "auto")."""
    p = {k: spec.get("default", "") for k, spec in e["params"].items()} | params
    dev = e.get("device_param")
    if dev:
        if p[dev] == "auto":
            p[dev] = "cuda" if free_vram >= vram_need + AUTO_DEVICE_MARGIN_MIB else "cpu"
        if p[dev] == "cpu":
            vram_need = 0
    values = {k: str(spec.get("map", {}).get(p[k], p[k])) for k, spec in e["params"].items()}
    f = Path(model["file"]) if model.get("file") else None
    values |= {"port": str(model["port"]), "models_dir": str(models_dir), "model_id": mid,
               "file": str(f or ""), "file_name": f.name if f else "", "file_dir": str(f.parent) if f else ""}

    def sub(s):
        return PLACEHOLDER.sub(lambda m: values[m.group(1)], expand(s))

    def has_empty(s):
        return any(not values[v] for v in PLACEHOLDER.findall(s))
    argv = []
    for a in e["command"]:
        if isinstance(a, list):
            if not any(has_empty(x) for x in a):
                argv += [sub(x) for x in a]
        elif sub(a):
            argv.append(sub(a))
    argv += [str(a) for a in model.get("extra_args", [])]
    env = {k: v for k, v in ((k, sub(v)) for k, v in e.get("env", {}).items()) if v}
    return argv, env, vram_need
