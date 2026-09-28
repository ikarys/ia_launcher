#!/usr/bin/env bash
# After moving this folder: puts the new path back into the venvs' scripts
# (shebangs "#!/old/path/venv-x/bin/python", activate, ...).
#   bash scripts/fix-venv-paths.sh /old/path/ia_launcher
set -euo pipefail
OLD="${1:?usage: $0 /old/path/ia_launcher}"
NEW="$(cd "$(dirname "$0")/.." && pwd)"
for v in "$NEW"/venv-*; do
  grep -rlI --exclude-dir=lib --exclude-dir=include -F "$OLD/" "$v" 2>/dev/null | while read -r f; do
    sed -i "s|$OLD/|$NEW/|g" "$f"
    echo "fixed: ${f#$NEW/}"
  done
done
