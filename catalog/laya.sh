#!/usr/bin/env bash
# Laya (convaiinnovations) decision model server: laya[serve] in $INSTALL_DIR/.venv, and its
# checkpoints in $MODELS_DIR/hf (the Hugging Face cache laya-serve reads).
source "$(dirname "$0")/lib.sh"
need uv
mkdir -p "$INSTALL_DIR"
cd "$INSTALL_DIR"
export HF_HUB_CACHE="${MODELS_DIR:-$HOME/hominfer_models}/hf"
[ -x .venv/bin/python ] || uv venv -q --python 3.12 .venv
step "Installing laya[serve]"
uv pip install -q --python .venv/bin/python "laya[serve]"
step "Downloading the checkpoints into $HF_HUB_CACHE"
.venv/bin/python - <<'EOF'
import importlib.metadata as md
import torch
from laya import Router
print("laya", md.version("laya"), "| torch", torch.__version__, "| cuda", torch.cuda.is_available())
r = Router(device="cpu")
r.preload()
print("checkpoints:", r.loaded)
EOF
