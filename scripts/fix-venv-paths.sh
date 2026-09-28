#!/usr/bin/env bash
# Apres un deplacement du dossier : remet le bon chemin dans les scripts des venvs
# (shebangs "#!/ancien/chemin/venv-x/bin/python", activate, ...).
#   bash setup/fix-venv-paths.sh /ancien/chemin/ia_launcher
set -euo pipefail
OLD="${1:?usage: $0 /ancien/chemin/ia_launcher}"
NEW="$(cd "$(dirname "$0")/.." && pwd)"
for v in "$NEW"/venv-*; do
  grep -rlI --exclude-dir=lib --exclude-dir=include -F "$OLD/" "$v" 2>/dev/null | while read -r f; do
    sed -i "s|$OLD/|$NEW/|g" "$f"
    echo "corrige : ${f#$NEW/}"
  done
done
