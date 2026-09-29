"""Hugging Face downloads into the models folder (one folder per repository)."""
import itertools
import json
import shutil
import time

from ..errors import LaunchError
from ..i18n import gib, tr
from ..infra import huggingface as hf
from ..infra.files import size_of, tail
from .jobs import Jobs

META = ".hominfer_meta.json"  # next to downloaded files: repository, commit, dates
LEGACY_META = ".ia_meta.json"  # pre-rename
FREE_MARGIN = 5 * 2**30


class Downloads:
    def __init__(self, models_dir, log_dir):
        """models_dir: () -> the models folder (a setting)."""
        self.models_dir, self.log_dir = models_dir, log_dir
        self.jobs = Jobs()
        self.ids = itertools.count(1)

    def target_of(self, repo):
        return self.models_dir() / repo.replace("/", "--")

    def any_running(self):
        return any(j.state == "running" for j in self.jobs.all())

    def busy(self, path):
        """A running download writes into path (or path is inside its folder)."""
        return any(j.state == "running" and (j.data["target"] == path or j.data["target"] in path.parents)
                   for j in self.jobs.all())

    def start(self, repo, files):
        info = hf.model_info(repo)
        sizes = {f["name"]: f["size"] for f in info["files"]}
        if not files or any(f not in sizes for f in files):
            raise LaunchError(tr("dl.pick_files"))
        total, free = sum(sizes[f] for f in files), shutil.disk_usage(self.models_dir()).free
        if total > free - FREE_MARGIN:
            raise LaunchError(tr("dl.no_space", size=gib(total / 2**20), free=gib(free / 2**20)))
        target = self.target_of(repo)
        if self.busy(target):
            raise LaunchError(tr("dl.running"))
        target.mkdir(parents=True, exist_ok=True)

        def work(job):
            code = job.run(hf.download_argv(repo, files, info["sha"], target))
            if job.state == "cancelled":
                return None
            if code:
                raise LaunchError(tr("dl.failed", code=code, log=tail(job.log_path, 3)))
            self._write_meta(target, info, files)
            return None
        n = next(self.ids)
        self.jobs.start(n, self.log_dir / f"download-{n}.log", work, busy_msg=tr("dl.running"),
                        repo=repo, files=files, total=total, target=target, base=size_of(target))

    @staticmethod
    def _write_meta(target, info, files):
        meta_f = target / META
        meta = json.loads(meta_f.read_text()) if meta_f.exists() else {"files": {}}
        now = time.strftime("%Y-%m-%dT%H:%M:%S")
        meta.update(repo=info["repo"], sha=info["sha"], modified=info["modified"], task=info["task"])
        for f in files:
            meta["files"][f] = {"downloaded": now}
        meta_f.write_text(json.dumps(meta, indent=2))

    def cancel(self, n):
        self.jobs.cancel(n)

    def status(self):
        return [{"id": j.key, "repo": j.data["repo"], "files": j.data["files"], "total": j.data["total"],
                 "state": j.state, "msg": j.msg,
                 "done": max(0, size_of(j.data["target"]) - j.data["base"]) if j.state == "running" else None}
                for j in sorted(self.jobs.all(), key=lambda j: -j.key)]
