"""Engine updates from their git clone: pull + build while models keep running.

A running process keeps the old binary (the linker writes a new file). A failed build goes
back to the previous commit and binary.
"""
import os
import shutil
import subprocess
from pathlib import Path

from ..errors import LaunchError
from ..i18n import tr
from ..infra import git
from .jobs import Jobs


class Updates:
    def __init__(self, registry, log_dir):
        self.registry, self.log_dir = registry, log_dir
        self.jobs = Jobs()

    def check(self, mid):
        return git.behind(self.registry.models[mid]["repo"])

    def start(self, mid):
        m = self.registry.models[mid]
        self.jobs.start(mid, self.log_dir / f"{mid}-update.log", lambda job: self._pull_and_build(job, m),
                        busy_msg=tr("upd.running"), msg="git pull…")

    @staticmethod
    def _pull_and_build(job, m):
        repo = Path(m["repo"])
        binary = repo / m["binary"]
        prev = binary.with_name(binary.name + ".prev")
        with open(job.log_path, "w") as log:
            def sh(*cmd):
                log.write(f"\n$ {' '.join(cmd)}\n")
                log.flush()
                return subprocess.run(cmd, cwd=repo, stdin=subprocess.DEVNULL, stdout=log,
                                      stderr=subprocess.STDOUT).returncode == 0

            if git.output(repo, "status", "--porcelain", "--untracked-files=no"):
                raise LaunchError(tr("upd.local_changes"))
            old = git.output(repo, "rev-parse", "--short", "HEAD")
            if not sh("git", "merge", "--ff-only", "@{u}"):
                raise LaunchError(tr("upd.pull_failed"))
            new = git.output(repo, "rev-parse", "--short", "HEAD")
            shutil.copy2(binary, prev)
            job.msg = tr("upd.building", old=old, new=new)
            if not sh("nice", "-n", "19", *m["build"]):
                sh("git", "reset", "--hard", old)
                os.replace(prev, binary)
                raise LaunchError(tr("upd.build_failed", old=old))
            return tr("upd.done", old=old, new=new)

    def status(self, mid):
        job = self.jobs.get(mid)
        return job and job.view(log_lines=20)
