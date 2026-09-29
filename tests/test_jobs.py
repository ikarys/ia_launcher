import threading

import pytest

from hominfer.errors import LaunchError
from hominfer.services.jobs import Jobs


def wait(job):
    for _ in range(100):
        if job.state != "running":
            return job
        threading.Event().wait(0.01)
    raise AssertionError("job still running")


def test_done_error_and_crash(tmp_path):
    jobs = Jobs()
    assert wait(jobs.start("a", tmp_path / "a.log", lambda job: "fine", busy_msg="busy")).view() == \
        {"state": "done", "msg": "fine"}

    def refuse(job):
        raise LaunchError("no way")
    assert wait(jobs.start("b", tmp_path / "b.log", refuse, busy_msg="busy")).msg == "no way"

    def crash(job):
        raise ValueError("boom")
    assert wait(jobs.start("c", tmp_path / "c.log", crash, busy_msg="busy")).msg == "ValueError: boom"


def test_one_running_job_per_key(tmp_path):
    jobs, release = Jobs(), threading.Event()
    job = jobs.start("k", tmp_path / "k.log", lambda job: release.wait(), busy_msg="busy")
    with pytest.raises(LaunchError, match="busy"):
        jobs.start("k", tmp_path / "k.log", lambda job: None, busy_msg="busy")
    release.set()
    wait(job)


def test_process_job_and_cancel(tmp_path):
    jobs = Jobs()
    job = wait(jobs.start("p", tmp_path / "p.log", lambda job: f"code {job.run(['echo', 'hi'])}", busy_msg="busy"))
    assert job.msg == "code 0" and (tmp_path / "p.log").read_text() == "hi\n"

    job = jobs.start("s", tmp_path / "s.log", lambda job: job.run(["sleep", "30"]), busy_msg="busy")
    while job.popen is None:
        threading.Event().wait(0.01)
    jobs.cancel("s")
    assert wait(job).state == "cancelled"
