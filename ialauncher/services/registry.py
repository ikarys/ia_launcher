"""engines.json and models.json: loaded, validated, and swapped as a whole under a lock."""
import copy
import json
import threading
from pathlib import Path

from ..domain import engine as engine_rules
from ..domain import model as model_rules
from ..errors import LaunchError
from ..i18n import tr
from ..infra.engine_files import is_installed
from ..infra.files import compact_json, read_json, write_atomic


def _models_text(cfg):
    """models.json readable by hand: one field per line, one param / profile per line."""
    j = lambda v: json.dumps(v, ensure_ascii=False)  # noqa: E731
    out = []
    for mid, c in cfg.items():
        fields = []
        for k, v in c.items():
            if isinstance(v, dict) and v:
                v = "{\n" + ",\n".join(f"      {j(kk)}: {j(vv)}" for kk, vv in v.items()) + "\n    }"
            else:
                v = j(v)
            fields.append(f"    {j(k)}: {v}")
        out.append(f"  {j(mid)}: {{\n" + ",\n".join(fields) + "\n  }")
    return "{\n" + ",\n".join(out) + "\n}\n"


class Registry:
    def __init__(self, engines_file, models_file, *, listen_port):
        self.engines_file, self.models_file, self.listen_port = engines_file, models_file, listen_port
        self.lock = threading.RLock()
        self.engines, self.cfg, self.models = {}, {}, {}
        self.reload_engines()
        self.reload_models()

    # -- engines
    def reload_engines(self):
        raw = read_json(self.engines_file, None)
        if raw is None:
            raise LaunchError(tr("cfg.engines_missing"))
        for eid, e in raw.items():
            engine_rules.validate(eid, e)
        with self.lock:
            self.engines = {eid: engine_rules.normalize(e) for eid, e in raw.items()}

    def installed(self, eid):
        return is_installed(self.engines[eid])

    def add_engine(self, eid, block):
        """Add an engine to engines.json. False when the id is already there (left untouched)."""
        with self.lock:
            raw = read_json(self.engines_file, {})
            if eid in raw:
                return False
            engine_rules.validate(eid, copy.deepcopy(block))
            raw[eid] = block
            write_atomic(self.engines_file, compact_json(raw) + "\n")
            self.reload_engines()
            return True

    # -- models
    def vram_need(self, c):
        """VRAM to have free before starting (a guard only: the engine takes what it needs).
        vram_mib from models.json when measured by hand, else estimated from the file size."""
        if c.get("vram_mib"):
            return c["vram_mib"]
        f = Path(c.get("file") or "/nonexistent")
        if not f.is_file():
            return 0
        if self.engines.get(c.get("engine"), {}).get("loads_dir"):  # every shard of the folder
            return model_rules.vram_estimate(sum(x.stat().st_size for x in f.parent.glob(f"*{f.suffix}")))
        return model_rules.vram_estimate(f.stat().st_size)

    def _checked(self, cfg):
        for mid, c in cfg.items():
            model_rules.validate(mid, c, self.engines, listen_port=self.listen_port)
        return {mid: model_rules.resolve(mid, c, self.engines[c["engine"]], vram_mib=self.vram_need(c))
                for mid, c in cfg.items()}

    def reload_models(self):
        with self.lock:
            cfg = read_json(self.models_file, {})
            self.cfg, self.models = cfg, self._checked(cfg)

    def edit_models(self, change):
        """Apply change(copy of the config), validate everything, write models.json, swap."""
        with self.lock:
            cfg = copy.deepcopy(self.cfg)
            change(cfg)
            models = self._checked(cfg)
            write_atomic(self.models_file, _models_text(cfg))
            self.cfg, self.models = cfg, models

    def process_patterns(self):
        """{model id: (process names, file to match)} for infra.processes.find."""
        return {mid: (m["procs"], m["match"]) for mid, m in self.models.items()}
