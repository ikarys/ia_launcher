# Contributing

Thanks for your interest! Bug reports, engine recipes, translations and fixes are all welcome.

## Development setup

```sh
just test          # creates venv-hominfer if needed, installs requirements-dev.txt, runs pytest
just run           # the launcher on http://localhost:8090
```

To try a change without touching your real configuration, run a second instance with its own port and
config folder:

```sh
HOMINFER_PORT=8091 HOMINFER_CONFIG_DIR=/tmp/hominfer-dev venv-hominfer/bin/python -m hominfer
```

The page has no build step: edit `web/`, reload the browser. Python changes need a restart of the
launcher.

Helpers:
- `scripts/show-commands.py`: print the command each model would run, per profile (starts nothing)
- `scripts/check-hf.py org/repo…`: print the launcher's verdicts for Hugging Face repositories
- `scripts/fix-venv-paths.sh /old/path`: repair the venvs after moving the project folder

## Guidelines

- **Keep it generic.** No model or engine name in the code: they belong in `engines.json`,
  `models.json` or the catalog.
- **Respect the layers** described in [docs/architecture.md](docs/architecture.md): `domain` stays pure
  (no I/O, no imports from other layers), system access goes through `infra`, the web layer only
  translates HTTP to service calls.
- **Small, focused files.** A module does one thing; split it before it becomes a catch-all.
- **Every user-facing text is a locale key**, added to every file of `locales/` (`just test` checks it).
- **English** for code, comments, docs and commit messages.
- **Add tests** for domain rules and services (`tests/`); they must not depend on a GPU or on the local
  configuration.
- **No new dependency** without a good reason: the server uses the standard library plus `psutil` and
  `huggingface_hub`, the page uses no framework.

## Adding an engine to the catalog

1. Add an entry to `catalog/catalog.json`: `label`, `desc` (`{"en", "fr"}`), `url`, `dir` (install
   folder, under `~/llm`), `script`, `disk_gb`, `minutes`, optional `min_cc` (minimum GPU compute
   capability), and `engine`: the block written to `engines.json` (see
   [docs/configuration.md](docs/configuration.md#enginesjson)).
2. Write `catalog/<engine>.sh`. Source `lib.sh`, check tools with `need`, use `cuda_toolkit` /
   `cuda_arch` / `git_checkout` when building, and install into `$INSTALL_DIR`. The script must be
   idempotent: running it again updates the engine. No sudo.
3. `just test` checks that the entry is valid and that its script exists.

## Pull requests

- One topic per pull request, with a short description of what changed and why.
- `just test` passes.
- For page changes, a screenshot helps (the Cyber theme is the house favourite).
