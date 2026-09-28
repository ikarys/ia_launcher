# IA Launcher

Local web page to start / stop local AI models (LLMs via Ninfer or llama.cpp,
Laya decision model) under WSL, and see their VRAM / RAM / CPU usage.

- Start / stop models, with profiles (context, sessions, vision, device…)
- Per-model VRAM tracking (inferred: `nvidia-smi` under WSL doesn't report per-process memory)
- Add / edit models and download from Hugging Face from the page
- Port conflict detection

## Getting started

Requirements: WSL (Ubuntu), [uv](https://github.com/astral-sh/uv), [just](https://github.com/casey/just), NVIDIA GPU.

```sh
just run              # http://0.0.0.0:8090 (reachable from the LAN)
just install-service  # or: systemd service started at WSL boot
```

The launcher venv (`venv-launcher`, dependency: `psutil`) is created on first run.
Install Laya with `setup/install-laya.sh`.


## Configuration

Models are described in `models.json` (local, not versioned), written by the
page. Without this file, the launcher starts with an empty list.

Environment variables: `IA_LAUNCHER_HOST` (default `0.0.0.0`),
`IA_LAUNCHER_PORT` (default `8090`), `HF_TOKEN` (private Hugging Face models).
