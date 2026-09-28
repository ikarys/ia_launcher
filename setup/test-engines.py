"""Print, for every model in models.json, the command and env the launcher would run
(nothing is started).
    venv-launcher/bin/python setup/test-engines.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import launcher  # noqa: E402

gpu = launcher.query_gpu()
for eid in launcher.ENGINES:
    print(f"engine {eid}: installed={launcher.installed(eid)}")
for c in launcher.INSTALLS.status(gpu and gpu["cc"]):
    print(f"catalog {c['id']}: {c['state']}" + ("" if c["compatible"] else f" (incompatible: {c['why']})"))
for mid, m in launcher.MODELS.items():
    for label, opts in {"default": {}, **m["profiles"]}.items():
        clean = {o["key"]: opts.get(o["key"], o["default"]) for o in m["options"]}
        cmd, env, vram = launcher.engine_run(mid, m["config"], m["fixed"] | clean, gpu)
        print(f"\n== {mid} [{label}]  vram={vram} MiB\n   $ {' '.join(cmd)}")
        for k, v in env.items():
            print(f"     {k}={v}")
