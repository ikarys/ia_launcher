"""Hugging Face Hub: model metadata (HTTP API) and downloads / cache removal (hf CLI)."""
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

from ..errors import LaunchError
from ..i18n import tr

API = "https://huggingface.co/api/models"
CLI = [sys.executable, "-m", "huggingface_hub.cli.hf"]  # huggingface_hub: requirements.txt
REPO = re.compile(r"[\w.-]+/[\w.-]+")


def _token():
    f = Path.home() / ".cache" / "huggingface" / "token"
    return os.environ.get("HF_TOKEN") or (f.read_text().strip() if f.exists() else None)


def _get(url):
    req = urllib.request.Request(url)
    if _token():
        req.add_header("authorization", f"Bearer {_token()}")
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)


def model_info(repo):
    """-> {repo, sha, modified, gated, tags, downloads, task, base, files: [{name, size}]}"""
    if not REPO.fullmatch(repo):
        raise LaunchError(tr("hf.bad_repo"))
    try:
        d = _get(f"{API}/{repo}?blobs=true")
    except urllib.error.HTTPError as e:
        raise LaunchError(tr({401: "hf.401", 404: "hf.404"}.get(e.code, "hf.http"), code=e.code))
    base = (d.get("cardData") or {}).get("base_model")
    return {"repo": repo, "sha": d["sha"], "modified": d.get("lastModified"), "gated": bool(d.get("gated")),
            "tags": d.get("tags", [])[:10], "downloads": d.get("downloads"), "task": d.get("pipeline_tag"),
            "base": (base[0] if isinstance(base, list) and base else base) or None,
            "files": [{"name": f["rfilename"], "size": f.get("size") or 0} for f in d["siblings"]]}


def gguf_quantizations(base, exclude, limit=6):
    """Most downloaded GGUF repos quantized from base, same model only (some finetunes declare
    the same base_model)."""
    found = _get(f"{API}?filter=base_model:quantized:{base}&filter=gguf&sort=downloads&direction=-1&limit={limit}")
    key = re.sub(r"[^a-z0-9]", "", base.split("/")[-1].lower())
    return [m["id"] for m in found if m["id"] != exclude and key in re.sub(r"[^a-z0-9]", "", m["id"].lower())]


def download_argv(repo, files, sha, target):
    return [*CLI, "download", repo, *files, "--revision", sha, "--local-dir", str(target)]


def cache_remove(repo, cache_dir):
    r = subprocess.run([*CLI, "cache", "rm", f"model/{repo}", "-y", "--cache-dir", str(cache_dir)],
                       capture_output=True, text=True, timeout=120)
    if r.returncode:
        raise LaunchError("hf cache rm : " + (r.stderr or r.stdout).strip()[-300:])
