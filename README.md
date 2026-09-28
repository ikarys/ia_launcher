# IA Launcher

Local web page to start / stop local AI models under WSL, and see their VRAM / RAM / CPU usage.
Generic: models and inference engines are configuration, nothing model- or engine-specific in the code.

- Start / stop models, with profiles (context, sessions, vision, device…)
- Per-model VRAM tracking (inferred: `nvidia-smi` under WSL doesn't report per-process memory)
- Add / edit models and download from Hugging Face from the page, with a "does it run here?" verdict
- Engine catalog: install an inference engine from the page when a model needs one (like LM Studio's runtimes)
- Port conflict detection
- Windows sleep blocked while a model is loaded (via WSL interop)

## Getting started

Requirements: WSL (Ubuntu), [uv](https://github.com/astral-sh/uv), [just](https://github.com/casey/just), NVIDIA GPU.

```sh
cp engines.example.json engines.json   # then describe your inference engines
just run              # http://0.0.0.0:8090 (reachable from the LAN)
just install-service  # or: systemd service started at WSL boot
```

The launcher venv (`venv-launcher`, see `requirements.txt`) is created and kept up to date by `run.sh`.
Inference engines live outside this project, in `~/llm/<engine>`: install them from the page (engine catalog).

## Engine catalog

`catalog/catalog.json` lists known engines (llama.cpp, vLLM, Ninfer, laya-serve): what they run, disk / time
estimates, minimum GPU generation, and the block they add to `engines.json`. Each has an idempotent install
script `catalog/<engine>.sh` (running it again updates / reconfigures). The page's "Moteurs d'inférence"
section installs them in the background; the Hugging Face verdicts suggest the missing engine.

No sudo: `catalog/lib.sh` builds against a CUDA toolkit made of NVIDIA's pip wheels (nvcc, cudart, cuBLAS)
in `~/llm/cuda-<version>/.venv`, shared by every engine build. System tools needed for builds:
`git cmake ninja-build build-essential`.

The page only picks a catalog id: scripts come from this repository, never from the page. An engine id
already in `engines.json` is left untouched.

## Configuration

Both files are local (not versioned).

**`engines.json`**: how to run each inference engine. Edited by hand only: the page can pick an
engine for a model but never write a command. Per engine:

| Key | Meaning |
|---|---|
| `label` | name shown in the page |
| `command` | argv (no shell). `~/` is expanded. A nested list is an optional group, dropped if a placeholder in it is empty |
| `env` | extra environment; a variable that ends up empty is dropped |
| `health`, `endpoint` | HTTP paths: readiness check, API shown in the page |
| `procs` | process names (basename of argv[0] or argv[1]) used to detect the engine |
| `match_file` | also match the model file in argv (one engine binary serving several models) |
| `kinds` | model kinds it runs (`llm`, `decision`, `tts`…) |
| `file_ext` | weight files it loads (`.gguf`…); empty = the engine fetches its own weights |
| `loads_dir` | the engine loads the model's whole folder (all shards), e.g. vLLM |
| `params` | settings per model: `label`, `default`, `values` (menu), `map` (value sent to the engine) |
| `device_param` | param holding `cpu` / `cuda` / `auto` (auto = GPU if enough free VRAM) |
| `provides_repos`, `uses`, `install_hint` | Hugging Face repos it downloads itself, where (under `~/ia_models`), how to install |
| `repo`, `build`, `binary` | git clone of the engine: "check update" / "update" buttons (pull + build) |

Placeholders in `command` / `env`: `{port}` `{file}` `{file_name}` `{file_dir}` `{models_dir}` `{model_id}`
and every param. An argument or env variable that ends up empty is dropped (optional param).

**`models.json`**: the models (engine, file, port, params, profiles), written by the page.
Without it, the launcher starts with an empty list.

**`settings.json`**: UI language (`en`, `fr`: one file per language in `locales/`) and default theme.

Environment variables: `IA_LAUNCHER_HOST` (default `0.0.0.0`), `IA_LAUNCHER_PORT` (default `8090`),
`IA_LAUNCHER_MODELS_DIR` (default `~/ia_models`), `HF_TOKEN` (private Hugging Face models).

## Architecture

The server is the `ialauncher` package (standard library + `psutil` + `huggingface_hub`), in layers whose
dependencies point inwards:

| Layer | Role |
|---|---|
| `web/` | HTTP: route table (URL → service call), presenters (JSON for the page), server (transport, errors) |
| `services/` | use cases: `supervisor` (start / stop / measure), `registry` (engines.json + models.json), `model_editor`, `library`, `downloads`, `catalog`, `updates`, `hub` (Hugging Face verdicts), `settings`, `jobs` (background jobs) |
| `domain/` | pure rules, no I/O: engine command building, model validation, compatibility verdicts, card state / VRAM |
| `infra/` | system access: GPU (`nvidia-smi`), processes, network, files, Hugging Face, git, Windows host |

`app.py` wires the services together (composition root), `__main__.py` starts the server.
Texts shown to the user come from `locales/<lang>.json` (same keys for the page and the server).

## Development

```sh
uv pip install --python venv-launcher/bin/python -r requirements-dev.txt
just test             # pytest: domain rules, jobs, catalog, locales
```

Tools:
- `scripts/show-commands.py`: print the command each model would run, per profile (starts nothing)
- `scripts/check-hf.py org/repo…`: print the launcher's verdicts for Hugging Face repositories
- `scripts/fix-venv-paths.sh /old/path`: repair the venvs after moving this folder
