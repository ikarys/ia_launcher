"""Model supervisor: start / stop models, and every few seconds a snapshot of their state and
usage (VRAM, RAM, CPU) for the page.

Models started here are stopped when the launcher stops. An engine started outside the launcher
is detected by its process names, and can be stopped too.
"""
import sys
import threading
import time

import psutil

from ..domain import engine as engine_rules
from ..domain.model import clean_options
from ..domain.status import model_state, model_vram
from ..errors import LaunchError
from ..i18n import gib, tr
from ..infra import net, processes
from ..infra.files import tail


class Supervisor:
    def __init__(self, registry, updates, *, gpu, keep_awake, log_dir, models_dir, default_baseline_mib):
        """gpu: () -> GPU state or None; keep_awake: .set(bool) holds off the host's sleep."""
        self.registry, self.updates, self.gpu, self.keep_awake = registry, updates, gpu, keep_awake
        self.log_dir, self.models_dir, self.default_baseline_mib = log_dir, models_dir, default_baseline_mib
        self.lock = threading.RLock()
        self.runs = {}       # started from here: id -> {popen, opts, vram_before, vram_load}
        self.errors = {}     # id -> message
        self.stopping = set()
        self.baseline = None  # VRAM used with no model, once seen
        self.pcache = {}     # pid -> psutil.Process (cpu_percent needs its history)
        self.snapshot = {"ready": False}
        self.ip = net.lan_ip()
        log_dir.mkdir(exist_ok=True)

    def baseline_mib(self):
        return self.baseline if self.baseline is not None else self.default_baseline_mib

    def find(self):
        return processes.find(self.registry.process_patterns())

    def is_running(self, mid):
        return bool(self.find().get(mid))

    def log(self, mid):
        return tail(self.log_dir / f"{mid}.log")

    # -- measures
    def run_forever(self, interval):
        while True:
            try:
                self.poll()
            except Exception as e:  # the page must keep answering
                print("poll:", e, file=sys.stderr)
            time.sleep(interval)

    def poll(self):
        gpu, procs = self.gpu(), self.find()
        if gpu and not gpu["pids"]:
            self.baseline = gpu["used"]
        on_gpu = {mid: bool(gpu) and any(p.pid in gpu["pids"] for p in ps) for mid, ps in procs.items()}
        with self.lock:
            models = {mid: self._model_view(mid, m, procs.get(mid, []), gpu, on_gpu)
                      for mid, m in self.registry.models.items()}
            alive = {p.pid for ps in procs.values() for p in ps}
            self.pcache = {pid: p for pid, p in self.pcache.items() if pid in alive}
        vm = psutil.virtual_memory()
        self.snapshot = {
            "ready": True, "time": time.time(), "lan_ip": self.ip,
            "gpu": gpu and {k: v for k, v in gpu.items() if k != "pids"} | {
                "baseline": self.baseline_mib(), "baseline_measured": self.baseline is not None},
            "ram": {"used_mib": round((vm.total - vm.available) / 2**20), "total_mib": round(vm.total / 2**20)},
            "cpu": {"pct": psutil.cpu_percent(None), "count": psutil.cpu_count() or 1},
            "models": models,
        }
        self.keep_awake.set(any(v["pids"] for v in models.values()))

    def _model_view(self, mid, m, ps, gpu, on_gpu):
        run = self._check_exit(mid, ps)
        state = model_state(stopping=mid in self.stopping, running=bool(ps), failed=mid in self.errors,
                            healthy=bool(ps) and net.http_ok(m["port"], m["health"]))
        if state == "ready" and run and run["vram_load"] is None and gpu and run["vram_before"] is not None:
            run["vram_load"] = max(0, gpu["used"] - run["vram_before"])
        vram, how = None, None
        if ps and gpu:
            vram, how = model_vram(mid, on_gpu, gpu["used"], self.baseline_mib(), self.baseline is not None,
                                   run and run["vram_load"])
        rss, cpu, started = self._usage(ps)
        ncpu = psutil.cpu_count() or 1
        return {
            "state": state, "managed": run is not None, "error": self.errors.get(mid),
            "pids": [p.pid for p in ps], "on_gpu": on_gpu.get(mid, False), "vram_mib": vram, "vram_how": how,
            "rss_mib": round(rss / 2**20) if ps else None,
            "cpu_pct": round(cpu, 1) if ps else None,  # 100 = one core
            "cpu_machine_pct": round(cpu / ncpu, 1) if ps else None,
            "uptime_s": round(time.time() - started) if started else None,
            "opts": run["opts"] if run else None,
            "update": self.updates.status(mid),
        }

    def _check_exit(self, mid, ps):
        """The run of a model started here, forgotten (with an error) if it died by itself."""
        run = self.runs.get(mid)
        if run and run["popen"].poll() is not None and mid not in self.stopping and not ps:
            self.errors[mid] = tr("run.died", code=run["popen"].returncode)
            self.runs.pop(mid)
            return None
        return run

    def _usage(self, ps):
        rss, cpu, started = 0, 0.0, None
        for p in ps:
            cp = self.pcache.setdefault(p.pid, p)
            try:
                with cp.oneshot():
                    rss += cp.memory_info().rss
                    cpu += cp.cpu_percent(None)
                    created = cp.create_time()
                    started = created if started is None else min(started, created)
            except psutil.Error:
                pass
        return rss, cpu, started

    # -- actions
    def start(self, mid, opts):
        m = self.registry.models[mid]
        with self.lock:
            if self.is_running(mid):
                raise LaunchError(tr("run.already"))
            for port, who in m["conflicts"].items():
                if net.port_open(port):
                    raise LaunchError(tr("run.conflict", who=who, port=port))
            if net.port_open(m["port"]):
                raise LaunchError(tr("run.port_busy", port=m["port"]))
            clean = clean_options(m, opts)
            gpu = self.gpu()
            free = gpu["total"] - gpu["used"] if gpu else 0
            argv, env, need = engine_rules.build_command(
                self.registry.engines[m["engine_id"]], mid, m["config"], m["fixed"] | clean,
                vram_need=m["vram_mib"], free_vram=free, models_dir=self.models_dir)
            if gpu and need and free < need:
                self._refuse_no_vram(mid, free, need)
            header = f"$ {' '.join(argv)}\n  {' '.join(f'{k}={v}' for k, v in env.items())}\n\n"
            popen = processes.spawn(argv, self.log_dir / f"{mid}.log", env=env, header=header)
            self.runs[mid] = {"popen": popen, "opts": clean, "vram_before": gpu and gpu["used"], "vram_load": None}
            self.errors.pop(mid, None)

    def _refuse_no_vram(self, mid, free, need):
        others = [self.registry.models[o]["name"] for o, s in self.snapshot.get("models", {}).items()
                  if o != mid and s.get("on_gpu") and o in self.registry.models]
        hint = tr("run.no_vram_hint", models=", ".join(others)) if others else ""
        raise LaunchError(tr("run.no_vram", free=gib(free), need=gib(need), hint=hint))

    def stop(self, mid):
        with self.lock:
            procs = self.find().get(mid, [])
            self.errors.pop(mid, None)
            if not procs:
                self.runs.pop(mid, None)
                return
            self.stopping.add(mid)
        threading.Thread(target=self._kill, args=(mid, procs), daemon=True).start()

    def _kill(self, mid, procs):
        run = self.runs.get(mid)
        try:
            if run:  # the whole group: e.g. an engine's watchdog script and its "sleep"
                processes.kill_group(run["popen"])
            processes.terminate(procs)
            if run:
                try:
                    run["popen"].wait(5)
                except Exception:
                    pass
        finally:
            with self.lock:
                self.runs.pop(mid, None)
                self.stopping.discard(mid)

    def shutdown(self):
        """Stop the models started here (the launcher is stopping)."""
        with self.lock:
            mine = list(self.runs)
        for mid in mine:
            procs = self.find().get(mid, [])
            if procs:
                print(f"stopping {mid}...", flush=True)
                self.stopping.add(mid)
                self._kill(mid, procs)
