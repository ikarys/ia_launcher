#!/usr/bin/env bash
# Copie le modele Qwen de D: vers ~/ia_models (lecture 9P chronometree).
# Blocs de 4 Mo + reprise sur la partie deja copiee : cp avec gros tampons
# echoue en "Cannot allocate memory" quand Ninfer occupe la RAM de WSL.
set -euo pipefail
mkdir -p ~/ia_models
SRC=/mnt/d/ninfer_models/Swift-Qwen3.8-27B-OrcaRouter-NVFP4-DFlash2-v3.ninfer
DST=~/ia_models/$(basename "$SRC")
PART="$DST.part"
BS=$((4 * 1024 * 1024))
free -g
touch "$PART"
DONE=$(( $(stat -c %s "$PART") / BS ))
echo "reprise au bloc $DONE"
S=$(date +%s)
dd if="$SRC" of="$PART" bs=$BS skip=$DONE seek=$DONE conv=notrunc iflag=fullblock status=none
E=$(date +%s)
[ "$(stat -c %s "$PART")" = "$(stat -c %s "$SRC")" ] || { echo "taille differente !"; exit 1; }
mv "$PART" "$DST"
echo "copie terminee en $((E - S)) s"
ls -la ~/ia_models
