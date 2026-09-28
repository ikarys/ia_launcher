#!/usr/bin/env bash
# llama.cpp (ggml-org): llama-server built with CUDA for this GPU, in $INSTALL_DIR.
source "$(dirname "$0")/lib.sh"
need git cmake ninja g++ uv
cuda_toolkit
git_checkout https://github.com/ggml-org/llama.cpp "$INSTALL_DIR"
cd "$INSTALL_DIR"
ARCH="$(cuda_arch)"
step "Configuring (CUDA, sm_$ARCH)"
cmake -S . -B build -G Ninja -DCMAKE_BUILD_TYPE=Release -DGGML_CUDA=ON -DLLAMA_CURL=OFF \
  -DCUDAToolkit_ROOT="$CUDA_ROOT" -DCMAKE_CUDA_COMPILER="$CUDA_ROOT/bin/nvcc" \
  -DCMAKE_CUDA_ARCHITECTURES="$ARCH"
step "Building llama-server (several minutes)"
nice -n 10 cmake --build build --target llama-server
build/bin/llama-server --version
