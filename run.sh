#!/usr/bin/env bash
# Runs IA Launcher in the foreground: http://0.0.0.0:8090 (reachable from the LAN).
# Creates its venv on first run, then keeps it in sync with requirements.txt.
# Ctrl+C stops the launcher AND the models it started.
set -euo pipefail
cd "$(dirname "$0")"
export PATH="$HOME/.local/bin:$PATH"
[ -x venv-launcher/bin/python ] || uv venv -q --python 3.12 venv-launcher
uv pip install -q --python venv-launcher/bin/python -r requirements.txt
exec venv-launcher/bin/python -m ialauncher
