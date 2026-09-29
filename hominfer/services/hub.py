"""Hugging Face repository check: verdict per variant on this machine, engine suggestions, and
smaller GGUF versions of the same model when an LLM doesn't fit."""
import shutil
from concurrent.futures import ThreadPoolExecutor

import psutil

from ..domain import compat
from ..domain.kinds import TASK_KIND
from ..infra import huggingface as hf


class HubAdvisor:
    def __init__(self, registry, catalog, library, gpu, baseline_mib):
        """gpu: () -> GPU state or None; baseline_mib: () -> VRAM used with no model."""
        self.registry, self.catalog, self.library = registry, catalog, library
        self.gpu, self.baseline_mib = gpu, baseline_mib

    def hardware(self):
        g, base = self.gpu(), self.baseline_mib()
        return {"gpu": g and g["name"], "cc": g and g["cc"],
                "vram_mib": g and g["total"], "vram_usable_mib": g and g["total"] - base,
                "vram_free_mib": g and g["total"] - g["used"],
                "ram_mib": round(psutil.virtual_memory().total / 2**20), "cpus": psutil.cpu_count(),
                "disk_free": shutil.disk_usage(self.library.dir).free}

    def _context(self, hw):
        return compat.Context(engines=self.registry.engines, hw=hw, installed=self.registry.installed,
                              lib_has=self.library.has,
                              suggest=lambda fmt, kind, repo: self.catalog.suggest(fmt, kind, repo, hw["cc"]))

    @staticmethod
    def _info(repo):
        info = hf.model_info(repo)
        info["kind"] = TASK_KIND.get(info["task"])
        for f in info["files"]:
            f["quant"] = compat.quant_of(f["name"])
        return info

    def check(self, repo):
        hw = self.hardware()
        ctx = self._context(hw)
        info = self._info(repo)
        info |= {"hardware": hw, "variants": compat.variants(repo, info["files"], info["kind"], ctx),
                 "alternatives": []}
        # GGUF versions from other repos only make sense for an LLM (llama-server doesn't run a
        # decision / TTS... model from a GGUF)
        if any(v["verdict"] in ("gpu", "installed") for v in info["variants"]) or info["kind"] not in (None, "llm"):
            return info
        base = info["base"] or repo
        try:
            candidates = hf.gguf_quantizations(base, exclude=repo)
        except Exception:
            return info

        def best(cand):  # the biggest variant that fits = the best quality
            try:
                ci = self._info(cand)
            except Exception:
                return None
            ok = [v for v in compat.variants(cand, ci["files"], ci["kind"], ctx) if v["verdict"] == "gpu"]
            return ok and {"repo": cand, "downloads": ci["downloads"], **max(ok, key=lambda v: v["size"])}
        with ThreadPoolExecutor(6) as ex:
            info["alternatives"] = [a for a in ex.map(best, candidates) if a]
        info["base_searched"] = base
        return info
