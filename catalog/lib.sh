#!/usr/bin/env bash
# Shared helpers for the engine install scripts (sourced, not run).
# Environment given by the launcher: INSTALL_DIR (where the engine goes), GPU_CC (e.g. 12.0).
# No sudo anywhere: the CUDA toolkit comes from NVIDIA's pip wheels, in a venv of its own.
set -euo pipefail
export PATH="$HOME/.local/bin:$PATH"

CUDA_VERSION="${CUDA_VERSION:-13.2}"
CUDA_VENV="${CUDA_VENV:-$HOME/llm/cuda-$CUDA_VERSION/.venv}"

step() { echo; echo "==> $*"; }

# need cmd... : stop with an explicit message if a system tool is missing
need() {
  local missing=()
  for c in "$@"; do command -v "$c" >/dev/null || missing+=("$c"); done
  if [ ${#missing[@]} -gt 0 ]; then
    echo "Outils manquants : ${missing[*]}"
    echo "A installer dans la WSL : sudo apt install ${missing[*]/g++/build-essential}"
    exit 1
  fi
}

# GPU architecture for nvcc: 12.0 -> 120a ("a": arch-specific features, e.g. FP4 on Blackwell)
cuda_arch() {
  local cc="${GPU_CC:-$(nvidia-smi --query-gpu=compute_cap --format=csv,noheader | head -1)}"
  local arch="${cc/./}"
  [ "${cc%%.*}" -ge 9 ] && arch="${arch}a"
  echo "$arch"
}

# CUDA toolkit (nvcc, headers, cudart, cuBLAS) from pip wheels; sets CUDA_ROOT and puts nvcc in PATH.
# CMake's FindCUDAToolkit wants unversioned .so names and a libcuda stub: added as links.
cuda_toolkit() {
  step "Toolkit CUDA $CUDA_VERSION (pip, $CUDA_VENV)"
  [ -x "$CUDA_VENV/bin/python" ] || uv venv -q --python 3.12 "$CUDA_VENV"
  uv pip install -q --python "$CUDA_VENV/bin/python" \
    "nvidia-cuda-nvcc==$CUDA_VERSION.*" "nvidia-cuda-runtime==$CUDA_VERSION.*" "nvidia-cuda-crt==$CUDA_VERSION.*" \
    "nvidia-cuda-cccl" "nvidia-nvvm" "nvidia-nvtx" "nvidia-cublas>=13,<14"
  CUDA_ROOT="$("$CUDA_VENV/bin/python" -c 'import nvidia, os; print(os.path.join(nvidia.__path__[0], "cu13"))')"
  local lib="$CUDA_ROOT/lib" f
  for f in "$lib"/lib*.so.*; do
    local base="${f%%.so.*}.so"
    [ -e "$base" ] || ln -s "$(basename "$f")" "$base"
  done
  if [ -e /usr/lib/wsl/lib/libcuda.so ]; then
    mkdir -p "$lib/stubs"
    ln -sfn /usr/lib/wsl/lib/libcuda.so "$lib/stubs/libcuda.so"
  fi
  export PATH="$CUDA_ROOT/bin:$PATH" CUDAToolkit_ROOT="$CUDA_ROOT"
  nvcc --version | tail -2
}

# git_checkout url dir : clone, or fast-forward an existing clone (local changes are kept: pull stops)
git_checkout() {
  if [ -d "$2/.git" ]; then
    step "Mise a jour de $2"
    git -C "$2" pull --ff-only
  else
    step "Clone de $1"
    git clone --depth 1 "$1" "$2"
  fi
}
