"""Background jobs (downloads, engine installs, engine updates): one thread each, a state, a
message and a log file."""
import threading

from ..errors import LaunchError
from ..infra import processes
from ..infra.files import tail


class Job:
    def __init__(self, key, log_path, msg, data):
        self.key, self.log_path, self.msg, self.data = key, log_path, msg, data
        self.state = "running"  # running | done | error | cancelled
        self.popen = None

    def run(self, argv, *, env=None, cwd=None):
        """Run a process logging to the job's log; -> exit code."""
        self.popen = processes.spawn(argv, self.log_path, env=env, cwd=cwd)
        return self.popen.wait()

    def view(self, log_lines=0):
        v = {"state": self.state, "msg": self.msg}
        return v | {"log": tail(self.log_path, log_lines)} if log_lines else v


class Jobs:
    def __init__(self):
        self.lock = threading.Lock()
        self.jobs = {}

    def running(self, key):
        return key in self.jobs and self.jobs[key].state == "running"

    def start(self, key, log_path, work, *, busy_msg, msg="", **data):
        """work(job) runs in a thread and returns the final message, or raises LaunchError."""
        with self.lock:
            if self.running(key):
                raise LaunchError(busy_msg)
            job = self.jobs[key] = Job(key, log_path, msg, data)
        threading.Thread(target=self._run, args=(job, work), daemon=True).start()
        return job

    @staticmethod
    def _run(job, work):
        try:
            msg = work(job)
            if job.state == "running":
                job.state, job.msg = "done", msg or ""
        except Exception as e:
            if job.state != "cancelled":
                job.state = "error"
                job.msg = str(e) if isinstance(e, LaunchError) else f"{type(e).__name__}: {e}"

    def cancel(self, key):
        job = self.jobs.get(key)
        if job and job.state == "running":
            job.state = "cancelled"
            if job.popen:
                processes.kill_group(job.popen)

    def get(self, key):
        return self.jobs.get(key)

    def all(self):
        return list(self.jobs.values())
