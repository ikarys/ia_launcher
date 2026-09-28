"""Print the launcher's verdicts (does it run here? which engine?) for Hugging Face repositories,
without starting the server.
    venv-launcher/bin/python scripts/check-hf.py org/repo [org/repo ...]"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from ialauncher.app import build  # noqa: E402

if len(sys.argv) < 2:
    sys.exit(__doc__)
app = build()
for repo in sys.argv[1:]:
    d = app.hub.check(repo)
    print(f"\n== {repo}  (task {d['task']} -> {d['kind']})")
    for v in d["variants"][:4]:
        print(f"   {v['verdict']:<12} {v['name'][:50]:<50} {v['why']}")
        if v.get("suggest"):
            print(f"   {'':<12} -> suggested engine: {v['suggest']['label']} ({v['suggest']['state']})")
    for a in d["alternatives"][:3]:
        print(f"   alternative: {a['repo']} {a['name']} ({a['verdict']})")
