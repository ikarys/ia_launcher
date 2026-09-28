"""Does a Hugging Face model run on this machine? Simple, explainable rules (no guessing).

Verdicts: installed | gpu | partial (GPU + RAM, slow) | no (too big) | incompatible | disk | extra.
"""
import re
from dataclasses import dataclass, field
from typing import Callable

from ..i18n import gib, loc, tr
from .kinds import kind_labels
from .model import vram_estimate

SHARD = re.compile(r"-\d{5}-of-\d{5}")
QUANT = re.compile(r"(?i)(?<![a-z0-9])(i?q\d(?:_[a-z0-9]+)*|p?t?q\d_\d|nvfp4|mxfp4|fp8|fp16|bf16|f16|f32|int[48]|awq"
                   r"|gptq|exl2|\d+(?:\.\d+)?bpw)(?![a-z0-9])")
MIN_CC = {"NVFP4": 10.0, "MXFP4": 10.0, "FP8": 8.9}  # minimum GPU generation for these formats
SMALL_FILES = (".json", ".txt", ".model", ".jinja", ".py")  # config / tokenizer of a safetensors repo


@dataclass
class Context:
    """What the rules need to know about this machine."""
    engines: dict                          # normalized engines.json
    hw: dict                               # cc, vram_usable_mib, vram_free_mib, ram_mib, disk_free
    installed: Callable[[str], bool]       # engine id -> its files are present
    lib_has: Callable[[str], bool]         # path under the models dir -> exists
    suggest: Callable = field(default=lambda fmt, kind, repo: None)  # catalog engine to install


def quant_of(name):
    m = QUANT.findall(name)
    return m[-1].upper() if m else None


def fit(size, fmt, quant, ctx, repo=None, kind=None):
    """-> (verdict, explanation)."""
    hw = ctx.hw
    for e in ctx.engines.values():  # engines fetching their own weights (e.g. from the HF cache)
        if repo in e.get("provides_repos", []):
            if all(ctx.lib_has(u) for u in e.get("uses", [])):
                return "installed", tr("fit.provided", engine=loc(e["label"]))
            if e.get("install_hint"):
                return "incompatible", tr("fit.self_download_hint", engine=loc(e["label"]), hint=e["install_hint"])
            return "incompatible", tr("fit.self_download", engine=loc(e["label"]))
    engines = [eid for eid, e in ctx.engines.items() if f".{fmt}" in e["file_ext"]]
    if not engines:
        return "incompatible", tr("fit.no_engine", fmt=fmt)
    fitting = [eid for eid in engines if kind is None or kind in ctx.engines[eid].get("kinds", [kind])]
    if not fitting:
        labels = ", ".join(loc(ctx.engines[eid]["label"]) for eid in engines)
        return "incompatible", tr("fit.wrong_kind", kind=kind_labels().get(kind, kind), engines=labels)
    if not any(ctx.installed(eid) for eid in fitting):
        return "incompatible", tr("fit.not_installed", fmt=fmt, engine=loc(ctx.engines[fitting[0]]["label"]))
    if quant in MIN_CC and (hw["cc"] or 0) < MIN_CC[quant]:
        return "incompatible", tr("fit.min_cc", quant=quant, cc=MIN_CC[quant], gpu_cc=hw["cc"])
    if size > hw["disk_free"]:
        return "disk", tr("fit.disk", size=gib(size / 2**20), free=gib(hw["disk_free"] / 2**20))
    need, usable = vram_estimate(size), hw["vram_usable_mib"] or 0
    if need <= usable:
        busy = tr("fit.busy") if need > (hw["vram_free_mib"] or 0) else ""
        return "gpu", tr("fit.gpu", need=gib(need), usable=gib(usable), busy=busy)
    if fmt == "gguf" and need <= usable + hw["ram_mib"] * 0.7:
        return "partial", tr("fit.partial", need=gib(need), usable=gib(usable))
    return "no", tr("fit.no_ram" if fmt == "gguf" else "fit.no", need=gib(need), usable=gib(usable))


def _format_of(name, has_safetensors):
    """File name -> (variant key, format), or None when it isn't model weights."""
    if name.endswith(".gguf"):
        return SHARD.sub("", name), "gguf"
    if name.endswith(".ninfer"):
        return name, "ninfer"
    if name.endswith(".safetensors") or (not has_safetensors and name.endswith((".bin", ".pt", ".pth"))):
        return tr("hf.safetensors_variant"), "safetensors"
    return None


def variants(repo, files, kind, ctx):
    """Files of a repository -> launchable variants (a split GGUF = one variant), with verdicts."""
    groups = {}
    has_st = any(f["name"].endswith(".safetensors") for f in files)
    for f in files:
        found = _format_of(f["name"], has_st)
        if found:
            key, fmt = found
            groups.setdefault(key, {"name": key, "format": fmt, "files": []})["files"].append(f)
    out = []
    for v in groups.values():
        v["size"] = sum(f["size"] for f in v["files"])
        v["quant"] = quant_of(repo if v["format"] == "safetensors" else v["name"])
        if v["format"] == "safetensors":  # without config / tokenizer the model doesn't load
            v["files"] += [f for f in files if f["size"] < 50 * 2**20 and f["name"].endswith(SMALL_FILES)]
        if "mmproj" in v["name"].lower():
            v["verdict"], v["why"] = "extra", tr("fit.mmproj")
        else:
            v["verdict"], v["why"] = fit(v["size"], v["format"], v["quant"], ctx, repo, kind)
            if v["verdict"] == "incompatible":  # a fix exists: not a dead end, it needs an install
                suggestion = ctx.suggest(v["format"], kind, repo)
                if suggestion:
                    v["suggest"] = suggestion
                    v["verdict"] = "install"
        v["files"] = [f["name"] for f in v["files"]]
        out.append(v)
    return sorted(out, key=lambda v: -v["size"])
