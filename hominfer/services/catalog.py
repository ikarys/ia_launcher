"""Engine catalog (catalog/): known engines, installed in the background from the page.

Each engine has an idempotent install script in ~/llm/<engine> (running it again updates /
reconfigures). The page only picks a catalog id: scripts come from the repository. Once
installed, the engine's block is added to engines.json if its id is free.
"""
import json
from pathlib import Path

from ..domain.engine import expand
from ..errors import LaunchError
from ..i18n import loc, tr
from ..infra.engine_files import is_installed
from .jobs import Jobs


class Catalog:
    def __init__(self, catalog_dir, registry, log_dir, models_dir):
        """models_dir: () -> the models folder (engines fetching their own weights put them there)."""
        self.dir, self.registry, self.log_dir, self.models_dir = catalog_dir, registry, log_dir, models_dir
        self.entries = json.loads((catalog_dir / "catalog.json").read_text())
        self.jobs = Jobs()

    def state(self, cid):
        """configured: in engines.json and installed | present: on disk (maybe partly) | available"""
        c = self.entries[cid]
        if cid in self.registry.engines and self.registry.installed(cid):
            return "configured"
        found = is_installed(c["engine"]) or c.get("detect") and (Path(expand(c["dir"])) / c["detect"]).exists()
        return "present" if found else "available"

    def compat(self, cid, gpu_cc):
        need = self.entries[cid].get("min_cc")
        if need and (gpu_cc or 0) < need:
            return False, tr("eng.min_cc", cc=need, gpu_cc=gpu_cc)
        return True, ""

    def suggest(self, fmt, kind, repo, gpu_cc):
        """Catalog engine that would run this model, if it isn't set up yet."""
        for cid, c in self.entries.items():
            e = c["engine"]
            runs = repo in e.get("provides_repos", []) or (
                f".{fmt}" in e.get("file_ext", []) and (kind is None or kind in e.get("kinds", [kind])))
            if runs and self.state(cid) != "configured" and self.compat(cid, gpu_cc)[0]:
                return {"id": cid, "label": loc(c["label"]), "disk_gb": c["disk_gb"], "minutes": c["minutes"],
                        "state": self.state(cid)}
        return None

    def install(self, cid, gpu_cc):
        if cid not in self.entries:
            raise LaunchError(tr("eng.unknown"))
        ok, why = self.compat(cid, gpu_cc)
        if not ok:
            raise LaunchError(why)
        c = self.entries[cid]

        def work(job):
            env = {"INSTALL_DIR": expand(c["dir"]), "MODELS_DIR": str(self.models_dir()), "GPU_CC": str(gpu_cc or "")}
            code = job.run(["bash", str(self.dir / c["script"])], env=env, cwd=self.dir)
            if code:
                raise LaunchError(tr("eng.failed", code=code))
            try:
                added = self.registry.add_engine(cid, c["engine"])
            except Exception as e:
                raise LaunchError(tr("eng.not_registered", err=e))
            return tr("eng.registered") if added else tr("eng.kept", id=cid)
        self.jobs.start(cid, self.log_dir / f"engine-{cid}.log", work, busy_msg=tr("eng.running"),
                        msg=tr("eng.installing", dir=c["dir"]))

    def status(self, gpu_cc):
        out = []
        for cid, c in self.entries.items():
            e, job = c["engine"], self.jobs.get(cid)
            ok, why = self.compat(cid, gpu_cc)
            out.append({"id": cid, "label": loc(c["label"]), "desc": loc(c["desc"]), "url": c["url"],
                        "dir": c["dir"], "disk_gb": c["disk_gb"], "minutes": c["minutes"],
                        "kinds": e.get("kinds", []), "file_ext": e.get("file_ext", []),
                        "state": self.state(cid), "compatible": ok, "why": why,
                        "job": job and job.view(log_lines=40)})
        return out
