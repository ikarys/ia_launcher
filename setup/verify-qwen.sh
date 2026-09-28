#!/usr/bin/env bash
# Compare octet par octet la copie de ~/ia_models avec l'original sur D:
F=Swift-Qwen3.8-27B-OrcaRouter-NVFP4-DFlash2-v3.ninfer
S=$(date +%s)
cmp "/mnt/d/ninfer_models/$F" "$HOME/ia_models/$F" && echo "IDENTIQUES"
echo "$(( $(date +%s) - S )) s"
