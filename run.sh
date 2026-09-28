#!/usr/bin/env bash
# Demarre l'IA Launcher en avant-plan : http://0.0.0.0:8090 (joignable depuis le LAN)
# (cree son venv au premier lancement). Ctrl+C arrete le launcher ET les
# modeles qu'il a lances.
set -euo pipefail
cd "$(dirname "$0")"
export PATH="$HOME/.local/bin:$PATH"
if [ ! -x venv-launcher/bin/python ]; then
  uv venv -q --python 3.12 venv-launcher
  uv pip install -q --python venv-launcher/bin/python psutil
fi
exec venv-launcher/bin/python launcher.py
