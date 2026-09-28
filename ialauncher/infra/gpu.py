"""NVIDIA GPU state from nvidia-smi.

Under WSL, nvidia-smi doesn't report per-process memory (N/A), only which PIDs use the GPU.
"""
import subprocess

QUERY = "name,memory.used,memory.total,utilization.gpu,temperature.gpu,power.draw,compute_cap"


def _num(s):
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def _smi(*args):
    return subprocess.run(["nvidia-smi", *args], capture_output=True, text=True, timeout=5).stdout


def query():
    """-> {name, used, total (MiB), util, temp, power, cc, pids} or None without a usable GPU."""
    try:
        line = _smi(f"--query-gpu={QUERY}", "--format=csv,noheader,nounits").strip().splitlines()[0]
        name, used, total, util, temp, power, cc = [x.strip() for x in line.split(",")]
        apps = _smi("--query-compute-apps=pid", "--format=csv,noheader").split()
        return {"name": name, "used": int(used), "total": int(total), "util": _num(util),
                "temp": _num(temp), "power": _num(power), "cc": _num(cc),
                "pids": {int(p) for p in apps if p.strip().isdigit()}}
    except Exception:
        return None
