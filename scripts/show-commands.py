"""Print, for every model of models.json and each of its profiles, the command and env the
launcher would run (nothing is started).
    venv-hominfer/bin/python scripts/show-commands.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from hominfer import config  # noqa: E402
from hominfer.domain import engine as engine_rules  # noqa: E402
from hominfer.domain.model import clean_options  # noqa: E402
from hominfer.infra import gpu as gpu_probe  # noqa: E402
from hominfer.services.registry import Registry  # noqa: E402
from hominfer.services.settings import Settings  # noqa: E402

models_dir = Settings(config.SETTINGS_FILE).models_dir()
registry = Registry(config.ENGINES_FILE, config.MODELS_FILE, listen_port=config.LISTEN_PORT)
gpu = gpu_probe.query()
free = gpu["total"] - gpu["used"] if gpu else 0
for eid in registry.engines:
    print(f"engine {eid}: installed={registry.installed(eid)}")
for mid, m in registry.models.items():
    for label, opts in {"default": {}, **m["profiles"]}.items():
        argv, env, vram = engine_rules.build_command(
            registry.engines[m["engine_id"]], mid, m["config"], m["fixed"] | clean_options(m, opts),
            vram_need=m["vram_mib"], free_vram=free, models_dir=models_dir)
        print(f"\n== {mid} [{label}]  vram={vram} MiB\n   $ {' '.join(argv)}")
        for k, v in env.items():
            print(f"     {k}={v}")
