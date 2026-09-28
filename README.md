# IA Launcher

Page web locale pour lancer / arrêter des modèles d'IA locaux (LLM via Ninfer ou
llama.cpp, modèle de décision Laya) sous WSL, et voir ce qu'ils consomment en
VRAM / RAM / CPU.

- Lancement / arrêt des modèles, avec profils (contexte, sessions, vision, device…)
- Suivi VRAM par modèle (déduit, `nvidia-smi` sous WSL ne donne pas la mémoire par processus)
- Ajout / édition des modèles et téléchargements Hugging Face depuis la page
- Détection des conflits de port

## Démarrage

Prérequis : WSL (Ubuntu), [uv](https://github.com/astral-sh/uv), [just](https://github.com/casey/just), GPU NVIDIA.

```sh
just run              # http://0.0.0.0:8090 (joignable depuis le LAN)
just install-service  # ou : service systemd lancé au boot de la WSL
```

Le venv du launcher (`venv-launcher`, dépendance : `psutil`) est créé au premier lancement.
Laya s'installe avec `setup/install-laya.sh`.

Côté Windows, `windows/ia-launcher.ps1` démarre le launcher dans WSL, ouvre la
page et bloque la mise en veille tant que la fenêtre est ouverte.

## Configuration

Les modèles sont décrits dans `models.json` (local, non versionné), écrit par la
page. Sans ce fichier, le launcher démarre avec une liste vide.

Variables d'environnement : `IA_LAUNCHER_HOST` (défaut `0.0.0.0`),
`IA_LAUNCHER_PORT` (défaut `8090`), `HF_TOKEN` (modèles Hugging Face privés).
