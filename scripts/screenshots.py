"""Capture the screenshots referenced by docs/how-to.md (docs/images/).

Playwright drives the user's Windows Chrome (no browser download). The launcher runs as a
demo instance: config, models folder and port live in a temp dir, the user's setup is
untouched. A fake downloaded Qwen3-TTS repository (sparse weights + its meta) makes the
library show a TTS file.

Setup (once):
    uv venv venv-shots
    uv pip install --python venv-shots/bin/python playwright pillow
    venv-shots/bin/python scripts/screenshots.py
"""
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHROME = "/mnt/c/Program Files/Google/Chrome/Application/chrome.exe"  # WSL interop: runs on Windows
OUT = ROOT / "docs" / "images"
REPO = "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice"
WIDTH = 1400  # same width as the existing screenshots


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def low_free_port(start=19001, n=100):
    """The WSL2 Windows->WSL localhost forwarding does not cover high (ephemeral) ports."""
    for p in range(start, start + n):
        s = socket.socket()
        try:
            s.bind(("127.0.0.1", p))
        except OSError:
            continue
        finally:
            s.close()
        return p
    raise SystemExit("no free port for Chrome remote debugging")


def demo_setup():
    """Temp config + models dir with the engines the demo pretends to have and a fake TTS download."""
    tmp = Path("/tmp/ia-shots")
    shutil.rmtree(tmp, ignore_errors=True)
    cfg, models = tmp / "config", tmp / "models"
    cfg.mkdir(parents=True)
    models.mkdir()
    catalog = json.loads((ROOT / "catalog" / "catalog.json").read_text())
    (cfg / "engines.json").write_text(json.dumps(
        {k: catalog[k]["engine"] for k in ("vllm", "vllm-omni")}, indent=2) + "\n")
    (cfg / "models.json").write_text("{}\n")
    (cfg / "settings.json").write_text(json.dumps(
        {"lang": "en", "theme": "cyber", "models_dir": str(models)}) + "\n")
    repo_dir = models / REPO.replace("/", "--")
    repo_dir.mkdir()
    with (repo_dir / "model.safetensors").open("wb") as w:
        os.ftruncate(w.fileno(), int(4.2 * 2**30))  # sparse: 4.2 GB, almost no disk
    (repo_dir / "config.json").write_text('{"architectures": ["Qwen3TTSForConditionalGeneration"]}\n')
    (repo_dir / ".ia_meta.json").write_text(json.dumps({
        "repo": REPO, "sha": "0c0e3051f", "modified": "2026-01-29T12:00:00", "task": "text-to-speech",
        "files": {"model.safetensors": {"downloaded": time.strftime("%Y-%m-%dT%H:%M:%S")}}}, indent=2) + "\n")
    return tmp, cfg, models


def start_launcher(cfg, models, port):
    env = dict(os.environ, IA_LAUNCHER_CONFIG_DIR=str(cfg), IA_LAUNCHER_MODELS_DIR=str(models),
               IA_LAUNCHER_PORT=str(port), IA_LAUNCHER_HOST="127.0.0.1")
    proc = subprocess.Popen([str(ROOT / "venv-launcher" / "bin" / "python"), "-m", "ialauncher"],
                            cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = f"http://127.0.0.1:{port}"
    for _ in range(150):
        try:
            urllib.request.urlopen(base + "/api/library", timeout=2)
            return proc, base
        except Exception:
            time.sleep(0.2)
    proc.kill()
    raise SystemExit("the launcher did not start")


def shoot(base, tmp):
    """CDP over TCP: WSL interop passes no file descriptors to Windows processes, so the
    remote-debugging-pipe Playwright uses by default does not survive; a port does."""
    from playwright.sync_api import sync_playwright
    profile = tmp / "chrome-profile"
    chrome, dbg = None, None
    for dbg in (low_free_port() + i for i in range(20)):
        chrome = subprocess.Popen([CHROME, f"--remote-debugging-port={dbg}",
                                   f"--user-data-dir={profile}",
                                   "--no-first-run", "--no-default-browser-check",
                                   f"--window-size={WIDTH},1000"],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(40):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{dbg}/json/version", timeout=1)
                break
            except Exception:
                time.sleep(0.2)
        else:
            chrome.terminate()
            chrome.wait()
            continue
        break
    else:
        raise SystemExit("Chrome did not open its remote-debugging port")
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.connect_over_cdp(f"http://127.0.0.1:{dbg}")
            page = browser.contexts[0].new_page()
            page.set_viewport_size({"width": WIDTH, "height": 1000})

            # (a) Hugging Face verdict: the TTS repository and the vLLM-Omni install suggestion
            page.goto(base + "/models")
            page.fill("#hfRepo", REPO)
            page.click("#hfForm button")
            page.wait_for_selector("#hfFiles button[data-install='vllm-omni']")
            page.wait_for_timeout(400)
            page.locator("section.panel:has(#hfForm)").screenshot(path=str(OUT / "hf-tts-verdict.png"))

            # (b) Settings: the engine catalog with vLLM-Omni and its install button
            page.goto(base + "/settings")
            page.wait_for_selector("#engTable tbody tr:has-text('vLLM-Omni')")
            page.wait_for_timeout(400)
            page.locator("#enginesSec").screenshot(path=str(OUT / "engines.png"))

            # (c) Library: the model form, engine prefilled for a TTS file
            page.goto(base + "/models")
            page.wait_for_selector("#libTable button[data-use]")
            page.click("#libTable button[data-use]")
            page.wait_for_function("document.querySelector('#modelDlg').open")
            page.wait_for_timeout(400)
            page.locator("#modelDlg").screenshot(path=str(OUT / "model-form.png"))
            page.close()
            browser.close()
    finally:
        chrome.terminate()
        chrome.wait(timeout=10)


def main():
    tmp, cfg, models = demo_setup()
    port = free_port()
    proc, base = start_launcher(cfg, models, port)
    try:
        shoot(base, tmp)
    finally:
        proc.terminate()
        proc.wait(timeout=10)
        shutil.rmtree(tmp, ignore_errors=True)
    print("saved:", *(str(p.relative_to(ROOT)) for p in sorted(OUT.glob("*.png"))), sep="\n  ")


if __name__ == "__main__":
    main()
