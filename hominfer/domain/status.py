"""What the model cards show: state, and per-model VRAM.

Per-model VRAM is inferred: under WSL nvidia-smi only tells which PIDs use the GPU.
- the only model on the GPU   -> VRAM used - baseline (display + WSL)   "live" / "estimate"
- several models on the GPU   -> VRAM delta measured while it loaded     "load"
- not on the GPU              -> 0                                       "cpu"
- several, no load measure    -> unknown                                 "shared"
"""


def model_state(*, stopping, running, healthy, failed):
    if stopping:
        return "stopping"
    if not running:
        return "error" if failed else "stopped"
    return "ready" if healthy else "starting"


def model_vram(mid, on_gpu, used_mib, baseline_mib, baseline_measured, load_mib):
    """on_gpu: {model id: uses the GPU}; load_mib: VRAM delta measured at load, or None.
    -> (VRAM in MiB or None, how)."""
    if not on_gpu[mid]:
        return 0, "cpu"
    if [m for m, v in on_gpu.items() if v] == [mid]:
        return max(0, used_mib - baseline_mib), "live" if baseline_measured else "estimate"
    if load_mib is not None:
        return load_mib, "load"
    return None, "shared"
