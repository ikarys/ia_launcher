"""Capture the screenshots referenced by README.md and docs/how-to.md (docs/images/).

Playwright drives a headless Chromium installed in WSL. The launcher runs as a demo
instance: config, models folder and port live in a temp dir, the user's setup is untouched.
A fake downloaded Qwen3-TTS repository (sparse weights + its meta) makes the library show
a TTS file, and a fake external ninfer-serve process makes the dashboard show a ready LLM.

Setup (once):
    uv venv venv-shots
    uv pip install --python venv-shots/bin/python playwright pillow
    sudo venv-shots/bin/python -m playwright install --with-deps chromium
    venv-shots/bin/python scripts/screenshots.py
"""
import json
import os
import shutil
import socket
import subprocess
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "images"
REPO = "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice"
WIDTH = 1400  # same width as the existing screenshots
FAKE_SMI = """#!/bin/sh
# Fakes an RTX 5090: VRAM jumps when the demo's ninfer-serve process is seen
case "$1" in
    --query-gpu*)
        if [ -n "$(pgrep -f 'hominfer-shots/ninfer-serve')" ]; then
            echo "NVIDIA GeForce RTX 5090, 31128, 32608, 97, 51, 459.00 W, 12.0"
        else
            echo "NVIDIA GeForce RTX 5090, 1536, 32608, 1, 37, 65.00 W, 12.0"
        fi
        ;;
    *) pgrep -f 'hominfer-shots/ninfer-serve' ;;
esac
"""

FAKE_SERVE = """#!/usr/bin/env python3
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer

class H(BaseHTTPRequestHandler):
    def do_GET(self):
        body = b'{"ok": true}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass

HTTPServer(("127.0.0.1", int(sys.argv[2])), H).serve_forever()
"""


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def sparse(path, gb):
    with path.open("wb") as w:
        os.ftruncate(w.fileno(), int(gb * 2**30))  # sparse: almost no disk


def demo_setup(tmp):
    """Config + models dir + a fake home: the engines the demo pretends to have installed."""
    cfg, home = tmp / "config", tmp / "home"
    models = home / "hominfer_models"
    cfg.mkdir(parents=True)
    models.mkdir(parents=True)
    catalog = json.loads((ROOT / "catalog" / "catalog.json").read_text())
    (cfg / "engines.json").write_text(json.dumps(
        {k: catalog[k]["engine"] for k in ("vllm", "vllm-omni", "ninfer", "laya")}, indent=2) + "\n")
    (cfg / "models.json").write_text("{}\n")
    (cfg / "settings.json").write_text(json.dumps(
        {"lang": "en", "theme": "cyber", "models_dir": "~/hominfer_models"}) + "\n")
    # vllm-omni stays "not installed": the HF verdict suggests installing it
    for p in ("llm/vllm/vllm-serve.sh", "llm/ninfer/build/apps/ninfer-serve",
              "llm/laya/.venv/bin/python", "llm/laya/.venv/bin/laya-serve"):
        f = home / p
        f.parent.mkdir(parents=True, exist_ok=True)
        f.touch()
    return cfg, models


def add_tts_repo(models):
    """A fake downloaded Qwen3-TTS repository so the library shows a TTS file."""
    repo_dir = models / REPO.replace("/", "--")
    repo_dir.mkdir()
    sparse(repo_dir / "model.safetensors", 4.2)
    (repo_dir / "config.json").write_text('{"architectures": ["Qwen3TTSForConditionalGeneration"]}\n')
    (repo_dir / ".hominfer_meta.json").write_text(json.dumps({
        "repo": REPO, "sha": "0c0e3051f", "modified": "2026-01-29T12:00:00", "task": "text-to-speech",
        "files": {"model.safetensors": {"downloaded": time.strftime("%Y-%m-%dT%H:%M:%S")}}}, indent=2) + "\n")


def add_dashboard_models(cfg, models, port):
    """The two models of the dashboard: an LLM and a decision model."""
    llm_file = models / "Swift-Qwen3.8-27B-OrcaRouter-NVFP4.ninfer"
    sparse(llm_file, 26)
    (cfg / "models.json").write_text(json.dumps({
        "Qwen38_27B": {
            "name": "Qwen 3.8 27B", "kind": "llm", "engine": "ninfer", "file": str(llm_file),
            "port": port, "task": "text-generation", "desc": "240k context. OpenAI / Anthropic API."},
        "laya_multilingual": {
            "name": "laya-multilingual", "kind": "decision", "engine": "laya",
            "port": free_port(), "task": "text-classification",
            "desc": "Decision model: typed choices, yes / no, scores. One pass, no text generation."}},
    indent=2) + "\n")
    return llm_file


def fake_gpu(tmp):
    smi = tmp / "bin" / "nvidia-smi"
    smi.parent.mkdir(parents=True, exist_ok=True)
    smi.write_text(FAKE_SMI)
    smi.chmod(0o755)
    return str(tmp / "bin")


def fake_external(llm_file, port, tmp):
    """A process named ninfer-serve whose argv carries the model file: seen as running, external."""
    serve = tmp / "ninfer-serve"
    serve.write_text(FAKE_SERVE)
    serve.chmod(0o755)
    return subprocess.Popen([str(serve), str(llm_file), str(port)],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def start_launcher(cfg, port, log, extra_path=""):
    env = dict(os.environ, HOME=str(Path(cfg).parent / "home"), HOMINFER_CONFIG_DIR=str(cfg),
               HOMINFER_PORT=str(port), HOMINFER_HOST="127.0.0.1")
    if extra_path:
        env["PATH"] = extra_path + os.pathsep + env["PATH"]
    with log.open("w") as err:
        proc = subprocess.Popen([str(ROOT / "venv-hominfer" / "bin" / "python"), "-m", "hominfer"],
                                cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=err)
    base = f"http://127.0.0.1:{port}"
    for _ in range(150):
        try:
            urllib.request.urlopen(base + "/api/library", timeout=2)
            return proc, base
        except Exception:
            time.sleep(0.2)
    proc.kill()
    raise SystemExit(f"the launcher did not start:\n{log.read_text()}")


def shoot(browser, proc, base, cfg, models, tmp):
    """Returns (proc, base) after the restart in (5)."""
    page = browser.new_page()
    page.set_viewport_size({"width": WIDTH, "height": 1000})

    # (1) First start: no model yet
    page.goto(base + "/")
    page.wait_for_selector("text=No model yet")
    page.wait_for_timeout(400)
    page.screenshot(path=str(OUT / "first-run.png"), full_page=True)

    # (2) Hugging Face verdict: the TTS repository and the vLLM-Omni install suggestion
    add_tts_repo(models)
    page.goto(base + "/models")
    page.fill("#hfRepo", REPO)
    page.click("#hfForm button")
    page.wait_for_selector("#hfFiles button[data-install='vllm-omni']")
    page.wait_for_timeout(400)
    page.locator("section.panel:has(#hfForm)").screenshot(path=str(OUT / "hf-tts-verdict.png"))

    # (3) Settings: the engine catalog with vLLM-Omni and its install button
    page.goto(base + "/settings")
    page.wait_for_selector("#engTable tbody tr:has-text('vLLM-Omni')")
    page.wait_for_timeout(400)
    page.locator("#enginesSec").screenshot(path=str(OUT / "engines.png"))

    # (4) Library: the model form, engine prefilled for a TTS file
    page.goto(base + "/models")
    page.wait_for_selector("#libTable button[data-use]")
    page.click("#libTable button[data-use]")
    page.wait_for_function("document.querySelector('#modelDlg').open")
    page.wait_for_timeout(400)
    page.locator("#modelDlg").screenshot(path=str(OUT / "model-form.png"))
    page.close()

    # (5) The two models: a fake external ninfer-serve for the LLM, then the full views.
    # models.json is only read at startup (the page edits it through the API), so restart.
    llm_port = free_port()
    llm_file = add_dashboard_models(cfg, models, llm_port)
    proc.terminate()
    proc.wait(timeout=10)
    proc, base = start_launcher(cfg, free_port(), tmp / "launcher2.log", fake_gpu(tmp))
    serve = fake_external(llm_file, llm_port, tmp)
    time.sleep(3)  # a poll cycle so the snapshot sees the process
    page = browser.new_page()
    page.set_viewport_size({"width": WIDTH, "height": 1000})
    page.goto(base + "/")
    page.wait_for_selector("text=Ready (external)")
    page.wait_for_timeout(400)
    page.screenshot(path=str(OUT / "dashboard.png"), full_page=True)
    page.goto(base + "/models")
    page.wait_for_selector("#libTable tr:has-text('Qwen3-TTS')")
    page.wait_for_timeout(400)
    page.screenshot(path=str(OUT / "models.png"), full_page=True)
    page.goto(base + "/settings")
    page.wait_for_selector("#engTable tbody tr:has-text('vLLM-Omni')")
    page.wait_for_timeout(400)
    page.screenshot(path=str(OUT / "settings.png"), full_page=True)
    page.close()
    serve.terminate()
    serve.wait(timeout=5)
    return proc, base


def main():
    tmp = Path("/tmp/hominfer-shots")
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    cfg, models = demo_setup(tmp)
    proc, base = start_launcher(cfg, free_port(), tmp / "launcher.log", fake_gpu(tmp))
    from playwright.sync_api import sync_playwright
    try:
        with sync_playwright() as pw:
            proc, base = shoot(pw.chromium.launch(headless=True), proc, base, cfg, models, tmp)
    finally:
        proc.terminate()
        proc.wait(timeout=10)
        shutil.rmtree(tmp, ignore_errors=True)
    print("saved:", *(str(p.relative_to(ROOT)) for p in sorted(OUT.glob("*.png"))), sep="\n  ")


if __name__ == "__main__":
    main()
