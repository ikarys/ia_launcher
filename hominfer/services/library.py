"""The models folder: what's in it (downloads, Hugging Face cache, files put by hand), what uses
what, deletion."""
import json
import shutil
import time
from pathlib import Path

from ..domain.compat import quant_of
from ..errors import LaunchError
from ..i18n import tr
from ..infra import huggingface as hf
from ..infra.files import size_of
from .downloads import META

WEIGHTS = (".gguf", ".safetensors", ".ninfer", ".bin", ".pt", ".pth", ".onnx")
HF_CACHE = "hf"  # engines fetching their own weights keep them in <models dir>/hf


def _date(ts):
    return time.strftime("%Y-%m-%d", time.localtime(ts))


class Library:
    def __init__(self, models_dir, registry, downloads):
        """models_dir: () -> the models folder (a setting)."""
        self.models_dir, self.registry, self.downloads = models_dir, registry, downloads

    @property
    def dir(self):
        return self.models_dir()

    def has(self, rel):
        return (self.dir / rel).exists()

    def used_by(self, p):
        """Names of the models whose file (or engine's own weights) is p or inside p."""
        p = str(p.resolve())
        names = set()
        for m in self.registry.models.values():
            uses = [m["config"]["file"]] if m["config"].get("file") else []
            uses += [self.dir / u for u in self.registry.engines[m["engine_id"]].get("uses", [])]
            if any(str(Path(f).resolve()) == p or str(Path(f).resolve()).startswith(p + "/") for f in uses):
                names.add(m["name"])
        return sorted(names)

    def items(self):
        out = []
        for p in sorted(self.dir.iterdir()):
            if p.name.startswith("."):
                continue
            if p.name == HF_CACHE:
                out += [self._cached_repo(d) for d in sorted(p.glob("models--*"))]
            else:
                out.append(self._entry(p))
        return out

    def _cached_repo(self, d):
        """A Hugging Face cache repo: snapshots are links to blobs (sometimes shared)."""
        ref = d / "refs" / "main"
        snaps = [f for f in d.glob("snapshots/*/**/*") if f.is_file()]
        return {"path": str(d.relative_to(self.dir)), "repo": d.name[8:].replace("--", "/"), "task": None,
                "source": "hf_cache", "sha": ref.read_text()[:7] if ref.exists() else None,
                "size": sum(f.stat().st_size for f in {f.resolve() for f in snaps}),
                "date": _date(d.stat().st_mtime), "used_by": self.used_by(d),
                "files": [{"name": "/".join(f.relative_to(d / "snapshots").parts[1:]), "quant": quant_of(f.name),
                           "size": f.stat().st_size} for f in snaps if f.name.endswith(WEIGHTS)]}

    def _entry(self, p):
        """A folder downloaded from the page (with its META) or a file / folder put by hand."""
        meta = json.loads((p / META).read_text()) if (p / META).exists() else None
        files = [p] if p.is_file() else [f for f in sorted(p.rglob("*"))
                                          if f.is_file() and f.name.endswith(WEIGHTS) and ".cache" not in f.parts]

        def downloaded(f):
            return meta and meta["files"].get(str(f.relative_to(p)), {}).get("downloaded", "")[:10]
        return {"path": p.name, "repo": meta and meta["repo"], "source": "hf" if meta else "local",
                "task": meta and meta.get("task"), "sha": meta and meta["sha"][:7],
                "hf_date": meta and (meta.get("modified") or "")[:10],
                "size": size_of(p), "date": _date(p.stat().st_mtime), "used_by": self.used_by(p),
                "files": [{"name": str(f.relative_to(p)) if f != p else f.name, "quant": quant_of(f.name),
                           "size": f.stat().st_size, "path": str(f.relative_to(self.dir)),
                           "downloaded": downloaded(f), "used_by": self.used_by(f)} for f in files]}

    def path(self, rel):
        """A path under the models folder coming from the page: refuse anything outside it."""
        root, cache = self.dir.resolve(), (self.dir / HF_CACHE).resolve()
        p = (self.dir / rel).resolve()
        if (p == root or not p.is_relative_to(root) or not p.exists()
                or (p.is_relative_to(cache) and not (p.parent == cache and p.name.startswith("models--")))):
            raise LaunchError(tr("lib.bad_path"))
        return p

    def delete(self, rel):
        p = self.path(rel)
        if self.used_by(p):
            raise LaunchError(tr("lib.used_by", models=", ".join(self.used_by(p))))
        if self.downloads.busy(p):
            raise LaunchError(tr("lib.downloading"))
        if p.parent == (self.dir / HF_CACHE).resolve():  # hf also cleans the shared blobs
            hf.cache_remove(p.name[8:].replace("--", "/"), p.parent)
        else:
            shutil.rmtree(p) if p.is_dir() else p.unlink()

    def free(self):
        return shutil.disk_usage(self.dir).free
