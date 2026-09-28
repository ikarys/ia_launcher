"""git commands on an engine's clone."""
import subprocess

from ..errors import LaunchError


def output(repo, *args, check=False, timeout=60):
    r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, timeout=timeout)
    if check and r.returncode:
        raise LaunchError(f"git {args[0]} : {r.stderr.strip() or r.returncode}")
    return r.stdout.strip()


def behind(repo):
    """git fetch, then the tracked branch's commits missing from HEAD (touches nothing else)."""
    output(repo, "fetch", "--quiet", check=True)
    return {"current": output(repo, "log", "-1", "--format=%h %cs", check=True),
            "branch": output(repo, "rev-parse", "--abbrev-ref", "@{u}", check=True),
            "behind": output(repo, "log", "--format=%h %cs %s", "HEAD..@{u}", check=True).splitlines()}
