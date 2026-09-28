"""Validate every catalog engine and print the command it would generate for a dummy model
(nothing is installed or started).
    venv-launcher/bin/python setup/test-catalog.py"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import launcher  # noqa: E402

gpu = launcher.query_gpu()
for cid, c in launcher.CATALOG.items():
    e = json.loads(json.dumps(c["engine"]))
    launcher.check_engine(cid, e)
    launcher.ENGINES[f"test-{cid}"] = e | {"params": {k: v if isinstance(v, dict) else {"label": v}
                                                     for k, v in e.get("params", {}).items()}}
    ext = (e.get("file_ext") or [""])[0]
    model = {"engine": f"test-{cid}", "port": 9000, "file": f"/models/org--repo/model{ext}" if ext else None}
    print(f"\n== {cid}  ({launcher.catalog_state(cid)})")
    for label, p in {"defaults": {}, "all set": {k: (v.get("values") or [["x"]])[-1][0]
                                                 for k, v in launcher.ENGINES[f"test-{cid}"]["params"].items()}}.items():
        cmd, env, _ = launcher.engine_run("my_model", model, p, gpu)
        print(f"   [{label}] $ {' '.join(cmd)}")
        for k, v in env.items():
            print(f"       {k}={v}")
