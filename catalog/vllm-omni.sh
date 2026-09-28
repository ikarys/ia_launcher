#!/usr/bin/env bash
# vLLM-Omni in $INSTALL_DIR/.venv (nightly wheel rebased on vLLM), plus vllm-omni-serve.sh which
# sets the environment vLLM needs under WSL. An existing install is kept (use its own upgrade).
source "$(dirname "$0")/lib.sh"
need uv
mkdir -p "$INSTALL_DIR"
cd "$INSTALL_DIR"
[ -x .venv/bin/python ] || uv venv -q --python 3.12 .venv
if .venv/bin/python -c "import vllm_omni" 2>/dev/null; then
  step "vLLM-Omni already installed: $(.venv/bin/python -c 'import vllm; print("vllm", vllm.__version__)')"
else
  step "Installing vLLM-Omni (several GB, nightly wheel)"
  uv pip install --python .venv/bin/python git+https://github.com/vllm-project/vllm-omni.git
fi
step "Writing the launch script vllm-omni-serve.sh"
cat > vllm-omni-serve.sh <<'EOF'
#!/usr/bin/env bash
# vllm serve --omni with the environment vLLM needs under WSL (written by the launcher's engine catalog).
set -euo pipefail
VENV="$(cd "$(dirname "$0")" && pwd)/.venv"
source "$VENV/bin/activate"
# WSL2: vLLM disables pinned memory by default; its v2 runner needs it ("UVA is not available")
export VLLM_WSL2_ENABLE_PIN_MEMORY=1
# FlashInfer JIT-compiles kernels: nvcc from the venv's nvidia pip packages (no system CUDA)
CU="$(python -c 'import nvidia, os; print(os.path.join(nvidia.__path__[0], "cu13"))')"
if [ -x "$CU/bin/nvcc" ]; then export CUDA_HOME="$CU" PATH="$CU/bin:$PATH"; fi
exec vllm serve --omni "$@"
EOF
chmod +x vllm-omni-serve.sh
.venv/bin/python -c "import vllm_omni, vllm, torch; print('vllm', vllm.__version__, '| torch', torch.__version__, '| cuda', torch.cuda.is_available())"
