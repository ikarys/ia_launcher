#!/usr/bin/env bash
# Ninfer (co-l): ninfer-serve built with CUDA for this GPU, in $INSTALL_DIR.
source "$(dirname "$0")/lib.sh"
need git cmake ninja g++ uv
cuda_toolkit
git_checkout https://github.com/co-l/ninfer.git "$INSTALL_DIR"
cd "$INSTALL_DIR"
git submodule update --init --recursive
ARCH="$(cuda_arch)"
step "Configuring (release preset, sm_$ARCH)"
cmake --preset release -DCUDAToolkit_ROOT="$CUDA_ROOT" -DCMAKE_CUDA_COMPILER="$CUDA_ROOT/bin/nvcc" \
  -DCMAKE_CUDA_ARCHITECTURES="$ARCH"
step "Building (several minutes)"
nice -n 10 cmake --build build
ls -la build/apps/ninfer-serve
