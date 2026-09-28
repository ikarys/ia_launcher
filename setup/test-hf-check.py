"""Print the launcher's verdicts (does it run here? which engine?) for Hugging Face repos,
without starting the server.
    venv-launcher/bin/python setup/test-hf-check.py org/repo [org/repo ...]"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import launcher  # noqa: E402

if len(sys.argv) < 2:
    sys.exit(__doc__)
for repo in sys.argv[1:]:
    d = launcher.hf_check(repo)
    print(f"\n== {repo}  (task {d['task']} -> {d['kind']})")
    for v in d["variants"][:4]:
        print(f"   {v['verdict']:<12} {v['name'][:50]:<50} {v['why']}")
        if v.get("suggest"):
            print(f"   {'':<12} -> suggested engine: {v['suggest']['label']} ({v['suggest']['state']})")
    for a in d["alternatives"][:3]:
        print(f"   alternative: {a['repo']} {a['name']} ({a['verdict']})")
