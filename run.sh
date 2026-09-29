#!/usr/bin/env bash
# Runs Hominfer in the foreground: http://0.0.0.0:8090 (reachable from the LAN).
# Creates its venv on first run, then keeps it in sync with requirements.txt.
# Ctrl+C stops the launcher AND the models it started.
set -euo pipefail
cd "$(dirname "$0")"
export PATH="$HOME/.local/bin:$PATH"
rm -rf venv-launcher  # pre-rename venv
[ -x venv-hominfer/bin/python ] || uv venv -q --python 3.12 venv-hominfer
uv pip install -q --python venv-hominfer/bin/python -r requirements.txt
exec venv-hominfer/bin/python -m hominfer
