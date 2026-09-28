#!/usr/bin/env bash
# Telecharge les checkpoints Laya dans ~/ia_models/hf (cache Hugging Face dedie)
set -euo pipefail
export HF_HUB_CACHE="$HOME/ia_models/hf"
mkdir -p "$HF_HUB_CACHE"
cd "$(dirname "$0")/.."
venv-laya/bin/python - <<'EOF'
from laya import Router
r = Router(device="cpu")
r.preload()
print("checkpoints charges :", r.loaded)
EOF
du -sh "$HF_HUB_CACHE"/* 2>/dev/null
