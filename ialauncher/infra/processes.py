"""Child processes: spawn (dying with the launcher), find by name, terminate."""
import ctypes
import os
import signal
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import psutil

# If the launcher is killed without stopping its children (SIGKILL, window closed), the kernel
# sends them SIGTERM when it dies (PR_SET_PDEATHSIG). That signal fires when the parent *thread*
# ends, hence one dedicated spawning thread living as long as the launcher (not HTTP threads).
_libc = ctypes.CDLL("libc.so.6", use_errno=True)
_SPAWNER = ThreadPoolExecutor(max_workers=1, thread_name_prefix="spawner")
PR_SET_PDEATHSIG = 1


def _die_with_launcher():
    _libc.prctl(PR_SET_PDEATHSIG, signal.SIGTERM)


def spawn(argv, log_path, *, env=None, cwd=None, header=""):
    """Start argv in its own process group, stdout/stderr to log_path (truncated)."""
    with open(log_path, "w") as log:
        if header:
            log.write(header)
            log.flush()
        return _SPAWNER.submit(
            subprocess.Popen, argv, env={**os.environ, **(env or {})}, cwd=cwd, stdin=subprocess.DEVNULL,
            stdout=log, stderr=subprocess.STDOUT, start_new_session=True,
            preexec_fn=_die_with_launcher).result()


def kill_group(popen, sig=signal.SIGTERM):
    try:
        os.killpg(popen.pid, sig)
    except ProcessLookupError:
        pass


def find(patterns):
    """patterns: {key: (names, match)} -> {key: [psutil.Process]}.

    A process belongs to a key when the basename of argv[0] or argv[1] is in names and, if match
    is set (one engine binary serving several models), match or its folder is in argv.
    Children follow their parent (e.g. vLLM's EngineCore, which holds the GPU memory)."""
    found = {key: [] for key in patterns}
    for p in psutil.process_iter(["pid", "cmdline"]):
        cmd = p.info["cmdline"] or []
        names = {os.path.basename(a) for a in cmd[:2]}
        for key, (wanted, match) in patterns.items():
            if names & set(wanted) and (not match or match in cmd or str(Path(match).parent) in cmd):
                found[key].append(p)
                break
    for ps in found.values():
        seen = {p.pid for p in ps}
        for p in list(ps):
            try:
                ps += [c for c in p.children(recursive=True) if c.pid not in seen and not seen.add(c.pid)]
            except psutil.Error:
                pass
    return found


def terminate(procs, timeout=20):
    """SIGTERM, then SIGKILL whatever is still alive after timeout seconds."""
    for p in procs:
        try:
            p.terminate()
        except psutil.Error:
            pass
    _, alive = psutil.wait_procs(procs, timeout=timeout)
    for p in alive:
        try:
            p.kill()
        except psutil.Error:
            pass
