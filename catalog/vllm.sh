#!/usr/bin/env bash
# vLLM in $INSTALL_DIR/.venv (torch matching the driver), plus vllm-serve.sh which sets the
# environment vLLM needs under WSL. An existing install is kept (use its own upgrade to update).
source "$(dirname "$0")/lib.sh"
need uv
mkdir -p "$INSTALL_DIR"
cd "$INSTALL_DIR"
[ -x .venv/bin/python ] || uv venv -q --python 3.12 .venv
if .venv/bin/python -c "import vllm" 2>/dev/null; then
  step "vLLM already installed: $(.venv/bin/python -c 'import vllm; print(vllm.__version__)')"
else
  step "Installing vLLM (several GB)"
  uv pip install --python .venv/bin/python vllm --torch-backend=auto
fi
step "Writing the launch script vllm-serve.sh"
cat > vllm-serve.sh <<'EOF'
#!/usr/bin/env bash
# vllm serve with the environment it needs under WSL (written by the launcher's engine catalog).
set -euo pipefail
VENV="$(cd "$(dirname "$0")" && pwd)/.venv"
source "$VENV/bin/activate"
# WSL2: vLLM disables pinned memory by default; its v2 runner needs it ("UVA is not available")
export VLLM_WSL2_ENABLE_PIN_MEMORY=1
# FlashInfer JIT-compiles kernels: nvcc from the venv's nvidia pip packages (no system CUDA)
CU="$(python -c 'import nvidia, os; print(os.path.join(nvidia.__path__[0], "cu13"))')"
if [ -x "$CU/bin/nvcc" ]; then export CUDA_HOME="$CU" PATH="$CU/bin:$PATH"; fi
exec vllm serve "$@"
EOF
chmod +x vllm-serve.sh
.venv/bin/python -c "import vllm, torch; print('vllm', vllm.__version__, '| torch', torch.__version__, '| cuda', torch.cuda.is_available())"
