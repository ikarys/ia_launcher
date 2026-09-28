"""IA Launcher: web page to start / stop local AI models and see their VRAM / RAM / CPU usage.

Models (models.json) run on inference engines (engines.json): nothing model- or engine-specific
lives in the code.

Layers (dependencies point inwards):
    web       HTTP routes and static page
    services  use cases: supervisor, registry, library, downloads, catalog, hub advisor
    domain    pure rules: engine command building, model validation, compatibility verdicts
    infra     system access: GPU, processes, network, JSON files, Hugging Face, git, Windows
"""
