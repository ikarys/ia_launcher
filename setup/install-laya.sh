#!/usr/bin/env bash
# Installe Laya (pip "laya[serve]") dans ~/ia_launcher/venv-laya
set -euo pipefail
cd "$(dirname "$0")/.."
export PATH="$HOME/.local/bin:$PATH"
[ -d venv-laya ] || uv venv -q --python 3.12 venv-laya
uv pip install -q --python venv-laya/bin/python "laya[serve]"
venv-laya/bin/python - <<'EOF'
import torch, importlib.metadata as md
print("laya", md.version("laya"), "| torch", torch.__version__, "| cuda", torch.cuda.is_available())
EOF
ls venv-laya/bin | grep -i laya
