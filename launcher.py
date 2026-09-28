#!/usr/bin/env python3
"""IA Launcher : page web pour lancer / arreter les modeles locaux
(Qwen via Ninfer, Laya) et voir ce qu'ils prennent en VRAM / RAM / CPU.

    just run   (ou service systemd : just install-service)   ->  http://<ip-lan>:8090 (ecoute sur 0.0.0.0)

Les modeles lances d'ici sont arretes quand le launcher s'arrete (just restart aussi).
Un Ninfer lance par l'ancien raccourci Windows est detecte et peut etre arrete.

VRAM par modele : sous WSL, nvidia-smi ne donne pas la memoire par processus
(N/A), seulement quels PID utilisent le GPU. On deduit donc :
  - un seul modele sur le GPU  -> VRAM utilisee - socle (affichage Windows + WSL)
  - plusieurs                  -> ecart de VRAM mesure pendant son chargement
"""
import ctypes
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import psutil

ROOT = Path(__file__).resolve().parent
HOME = Path.home()
MODELS_DIR = HOME / "ia_models"
LOG_DIR = ROOT / "logs"
LISTEN_HOST = os.environ.get("IA_LAUNCHER_HOST", "0.0.0.0")
LISTEN_PORT = int(os.environ.get("IA_LAUNCHER_PORT", "8090"))
POLL_S = 2.0
# VRAM prise par l'affichage Windows + WSL sans modele (remplacee par la mesure
# reelle des qu'on observe le GPU sans aucun processus de calcul)
DEFAULT_BASELINE_MIB = 1500



class LaunchError(Exception):
    pass


# Si le launcher est tue sans pouvoir arreter ses modeles (SIGKILL, fenetre
# fermee), le noyau leur envoie SIGTERM a sa mort (PR_SET_PDEATHSIG).
# Ce signal part quand le *thread* parent se termine, d'ou un thread dedie aux
# lancements qui vit aussi longtemps que le launcher (pas les threads HTTP).
_libc = ctypes.CDLL("libc.so.6", use_errno=True)
SPAWNER = ThreadPoolExecutor(max_workers=1, thread_name_prefix="spawner")


def _die_with_launcher():
    _libc.prctl(1, signal.SIGTERM)  # PR_SET_PDEATHSIG


# --- Moteurs ---------------------------------------------------------------------
# Un moteur = comment lancer un type de modele. Liste fixe dans le code : la page
# (joignable depuis le LAN) ne peut choisir qu'un de ces moteurs, jamais une commande.
# "params" : parametres reglables dans models.json / le formulaire (cle -> libelle).

NINFER_SCRIPT = "/mnt/d/ninfer/start-ninfer.sh"
LLAMA_PRISM = HOME / "llm" / "llama.cpp-prism"


def ninfer_run(m, p, gpu):
    f = Path(m["file"])
    env = {
        "MODEL": f.name,
        "MODEL_DIR": str(f.parent),
        "PORT": str(m["port"]),
        "CONCURRENCY": p.get("concurrency", "4"),
        "VISION": "0" if p.get("vision") == "off" else "1",
    }
    if p.get("ctx"):
        env["MAX_CONTEXT"] = env["KV_CAPACITY"] = p["ctx"]
    for k, var in (("spec", "SPEC"), ("draft", "DRAFT")):
        if p.get(k):
            env[var] = p[k]
    return ["bash", NINFER_SCRIPT], env, vram_need(m)


def llama_run(m, p, gpu):
    cmd = [str(LLAMA_PRISM / "build" / "bin" / "llama-server"), "-m", m["file"],
           "--host", "0.0.0.0", "--port", str(m["port"]),
           "-ngl", p.get("ngl", "999"), "-fa", p.get("flash_attn", "on"),
           "-c", p.get("ctx", "0"), "-np", p.get("parallel", "1"), *m.get("extra_args", [])]
    return cmd, {}, vram_need(m)


def laya_run(m, p, gpu):
    device = p.get("device", "cpu")
    if device == "auto":
        free = gpu["total"] - gpu["used"] if gpu else 0
        device = "cuda" if free >= 3000 else "cpu"
    # ponytail: 1 seul checkpoint resident (multilingual, ~1,4 Go VRAM ; ~35 ms/req sur CPU).
    # Un texte anglais recharge le checkpoint english a la volee ; LAYA_MAX_LOADED=2 si ca arrive souvent.
    env = {
        "LAYA_HOST": "0.0.0.0",
        "LAYA_PORT": str(m["port"]),
        "LAYA_DEVICE": device,
        "LAYA_PRELOAD": "1",
        "LAYA_MODELS": "multilingual",
        "LAYA_MAX_LOADED": "1",
        "HF_HUB_CACHE": str(MODELS_DIR / "hf"),
        "HF_HUB_OFFLINE": "1",
    }
    # via le python du venv : le shebang de laya-serve contient le chemin absolu du
    # venv et casse si le dossier est deplace (argv[1] reste "laya-serve" pour discover())
    venv_bin = ROOT / "venv-laya" / "bin"
    return [str(venv_bin / "python"), str(venv_bin / "laya-serve")], env, (vram_need(m) if device == "cuda" else 0)


def vram_estimate(size):
    # ponytail: poids +10 % + 1 Go (KV a contexte moyen, runtime) ; mesurer et fixer vram_mib si un gros contexte deborde
    return round(size / 2**20 * 1.1 + 1024)


def vram_need(c):
    """VRAM demandee avant lancement (seulement un garde-fou : le moteur prend ce qu'il lui faut).
    vram_mib dans models.json si mesure a la main, sinon estimee depuis la taille du fichier."""
    if c.get("vram_mib"):
        return c["vram_mib"]
    f = Path(c.get("file") or "/nonexistent")
    return vram_estimate(f.stat().st_size) if f.is_file() else 0


ENGINES = {
    "ninfer": {
        "label": "Ninfer", "run": ninfer_run, "needs_file": True,
        "health": "/health", "endpoint": "/v1",
        # basenames de argv[0] / argv[1] qui identifient ses processus
        # ponytail: pas de distinction par fichier, 2 modeles ninfer lances en meme temps se confondraient
        "procs": ["ninfer-serve", "start-ninfer.sh"],
        # clone git du moteur : boutons "Vérifier MAJ" / "Mettre à jour" (pull + build, sans redemarrer)
        "repo": str(HOME / "llm" / "ninfer"),
        "build": ["cmake", "--build", "build"],  # config CMake/Ninja deja en cache dans build/
        "binary": "build/apps/ninfer-serve",
        "params": {"ctx": "Contexte max (tokens)", "concurrency": "Sessions parallèles",
                   "vision": {"label": "Vision", "values": [["on", "activée"], ["off", "désactivée (libère de la VRAM)"]]},
                   "spec": {"label": "Décodage spéculatif", "values": [["dflash2", "DFlash2"], ["mtp", "MTP"]]},
                   "draft": "Tokens de brouillon"},
    },
    "llama.cpp-prism": {
        "label": "llama.cpp (prism)", "run": llama_run, "needs_file": True,
        "health": "/health", "endpoint": "/v1",
        "procs": ["llama-server"], "match_file": True,  # plusieurs GGUF : reconnus par le fichier dans argv
        "repo": str(LLAMA_PRISM),
        "build": ["cmake", "--build", "build", "--target", "llama-server"],
        "binary": "build/bin/llama-server",
        "params": {"ctx": "Contexte (total, partagé entre sessions)", "parallel": "Sessions parallèles",
                   "ngl": "Couches sur GPU (999 = toutes)",
                   "flash_attn": {"label": "Flash attention", "values": [["on", "activée"], ["off", "désactivée"], ["auto", "auto"]]}},
    },
    "laya": {
        "label": "laya-serve", "run": laya_run, "needs_file": False,
        "health": "/health", "endpoint": "/v1/systemone",
        "procs": ["laya-serve"],
        "uses": ["hf/models--convaiinnovations--laya"],  # dans ~/ia_models : protege de la suppression
        "params": {"device": {"label": "Calcul sur", "values": [["cpu", "CPU (~35 ms, 0 VRAM)"],
                                                                ["auto", "auto (GPU si assez de VRAM)"],
                                                                ["cuda", "GPU (~15 ms, ~1,4 Go)"]]}},
    },
}

for _e in ENGINES.values():
    _e["params"] = {k: v if isinstance(v, dict) else {"label": v} for k, v in _e["params"].items()}

KINDS = {"llm": "LLM", "decision": "Décision", "tts": "Voix (TTS)", "stt": "Transcription (STT)",
         "embedding": "Embeddings", "image": "Image", "video": "Vidéo"}
# tache Hugging Face (pipeline_tag) -> section de la page
TASK_KIND = {
    "text-generation": "llm", "image-text-to-text": "llm", "audio-text-to-text": "llm",
    "video-text-to-text": "llm", "any-to-any": "llm", "visual-question-answering": "llm",
    "text-classification": "decision", "zero-shot-classification": "decision", "token-classification": "decision",
    "text-to-speech": "tts", "text-to-audio": "tts",
    "automatic-speech-recognition": "stt",
    "feature-extraction": "embedding", "sentence-similarity": "embedding", "text-ranking": "embedding",
    "text-to-image": "image", "image-to-image": "image", "text-to-video": "video", "image-to-video": "video",
}


# --- Modeles (models.json) ----------------------------------------------------------
# Un modele = moteur + fichier + port + params. Valeur de param : "x" (fixe) ou
# ["x", "y"] / [["x", "libellé"], ...] (menu dans la page, la 1re = defaut).

CONFIG = ROOT / "models.json"
WORD = re.compile(r"\w+")
VALUE = re.compile(r"[\w.:/+-]{1,200}")


def choices_of(v):
    vals = v if isinstance(v, list) else [v]
    return [c if isinstance(c, list) else [str(c), str(c)] for c in vals]


def labelled(spec, v):
    """Choix du menu de la carte ; libelles du moteur pour les valeurs sans libelle."""
    names = dict(spec.get("values", []))
    return [[x, names.get(x, lbl) if lbl == x else lbl] for x, lbl in choices_of(v)]


def check_model(mid, c):
    """Valide une entree de models.json (le formulaire ecrit dedans : c'est une frontiere de confiance)."""
    def need(cond, msg):
        if not cond:
            raise LaunchError(f"{mid} : {msg}")
    need(WORD.fullmatch(mid), "identifiant : lettres, chiffres, _ uniquement")
    e = ENGINES.get(c.get("engine"))
    need(e, f"moteur inconnu ({', '.join(ENGINES)})")
    need(WORD.fullmatch(str(c.get("kind", ""))), "kind : lettres, chiffres, _ uniquement")
    need(isinstance(c.get("name"), str) and c["name"].strip(), "nom manquant")
    need(isinstance(c.get("port"), int) and 1024 <= c["port"] <= 65535 and c["port"] != LISTEN_PORT, "port invalide")
    need(re.fullmatch(r"[\w-]*", str(c.get("task", ""))), "tâche invalide")
    need(isinstance(c.get("vram_mib", 0), int) and c.get("vram_mib", 0) >= 0, "vram_mib : entier en Mio")
    if e["needs_file"]:
        need(isinstance(c.get("file"), str) and Path(c["file"]).is_file(), f"fichier introuvable : {c.get('file')}")
    for k, v in c.get("params", {}).items():
        need(k in e["params"], f"param inconnu pour {c['engine']} : {k} ({', '.join(e['params'])})")
        allowed = [x for x, _ in e["params"][k].get("values", [])]
        for val, _ in choices_of(v):
            need(VALUE.fullmatch(str(val)), f"{k} : valeur invalide {val!r}")
            need(not allowed or val in allowed, f"{k} : {val!r} pas dans {', '.join(allowed)}")
    for name, prof in c.get("profiles", {}).items():
        for k, v in prof.items():
            need(v in [x for x, _ in choices_of(c.get("params", {}).get(k, []))], f"profil {name} : {k}={v} hors menu")


def resolve(mid, c):
    """Entree de models.json + son moteur -> ce qu'utilisent le launcher et la page."""
    e = ENGINES[c["engine"]]
    params = c.get("params", {})
    return {
        "kind": c["kind"], "name": c["name"], "desc": c.get("desc", ""), "task": c.get("task"),
        "engine": e["label"], "engine_id": c["engine"],
        "port": c["port"], "health": e["health"], "endpoint": e["endpoint"],
        "procs": e["procs"], "match": c.get("file") if e.get("match_file") else None,
        "conflicts": {int(k): v for k, v in c.get("conflicts", {}).items()},
        "repo": e.get("repo"), "build": e.get("build"), "binary": e.get("binary"),
        "fixed": {k: str(v) for k, v in params.items() if not isinstance(v, list)},
        "vram_mib": vram_need(c),
        "options": [{"key": k, "label": e["params"][k]["label"], "choices": labelled(e["params"][k], v),
                     "default": choices_of(v)[0][0]}
                    for k, v in params.items() if isinstance(v, list)],
        "profiles": c.get("profiles", {}),
        "config": c,
    }


def load_models():
    cfg = json.loads(CONFIG.read_text()) if CONFIG.exists() else {}  # models.json : local, hors git
    for mid, c in cfg.items():
        check_model(mid, c)
    return cfg, {mid: resolve(mid, c) for mid, c in cfg.items()}


def save_models(cfg):
    """Ecrit models.json lisible a la main : un champ par ligne, un param / profil par ligne."""
    j = lambda v: json.dumps(v, ensure_ascii=False)
    out = []
    for mid, c in cfg.items():
        fields = []
        for k, v in c.items():
            if isinstance(v, dict) and v:
                v = "{\n" + ",\n".join(f"      {j(kk)}: {j(vv)}" for kk, vv in v.items()) + "\n    }"
            else:
                v = j(v)
            fields.append(f"    {j(k)}: {v}")
        out.append(f"  {j(mid)}: {{\n" + ",\n".join(fields) + "\n  }")
    tmp = CONFIG.with_suffix(".tmp")
    tmp.write_text("{\n" + ",\n".join(out) + "\n}\n")
    os.replace(tmp, CONFIG)


CFG, MODELS = load_models()
CONFIG_LOCK = threading.Lock()


def edit_config(fn):
    """Applique fn(copie de la config), valide tout, ecrit models.json, puis bascule MODELS."""
    global CFG, MODELS
    with CONFIG_LOCK:
        cfg = json.loads(json.dumps(CFG))
        fn(cfg)
        for mid, c in cfg.items():
            check_model(mid, c)
        save_models(cfg)
        CFG, MODELS = cfg, {mid: resolve(mid, c) for mid, c in cfg.items()}


def reload_config():
    global CFG, MODELS
    with CONFIG_LOCK:
        CFG, MODELS = load_models()


def not_running(mid):
    if discover().get(mid):
        raise LaunchError("Ce modèle tourne : arrête-le d'abord.")


# --- Mesures --------------------------------------------------------------------

def _num(s):
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def query_gpu():
    try:
        line = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.used,memory.total,utilization.gpu,temperature.gpu,power.draw,compute_cap",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5).stdout.strip().splitlines()[0]
        name, used, total, util, temp, power, cc = [x.strip() for x in line.split(",")]
        apps = subprocess.run(["nvidia-smi", "--query-compute-apps=pid", "--format=csv,noheader"],
                              capture_output=True, text=True, timeout=5).stdout.split()
        return {"name": name, "used": int(used), "total": int(total), "util": _num(util),
                "temp": _num(temp), "power": _num(power), "cc": _num(cc),
                "pids": {int(p) for p in apps if p.strip().isdigit()}}
    except Exception:
        return None


def discover():
    """{model_id: [psutil.Process]} d'apres argv[0] / argv[1] (+ le fichier du modele dans argv si
    le moteur sert plusieurs modeles, ex. llama-server)."""
    models = MODELS
    found = {mid: [] for mid in models}
    for p in psutil.process_iter(["pid", "cmdline"]):
        cmd = p.info["cmdline"] or []
        names = {os.path.basename(a) for a in cmd[:2]}
        for mid, m in models.items():
            if names & set(m["procs"]) and (not m["match"] or m["match"] in cmd):
                found[mid].append(p)
                break
    return found


def http_ok(port, path, timeout=1.5):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=timeout) as r:
            return r.status == 200
    except Exception:
        return False


def port_open(port):
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def lan_ip():
    for addrs in psutil.net_if_addrs().values():
        for a in addrs:
            if a.family == socket.AF_INET and re.match(r"192\.168\.|172\.(1[6-9]|2\d|3[01])\.", a.address):
                return a.address
    return None


def check_update(repo):
    """git fetch puis commits de la branche suivie absents de HEAD. Ne touche ni au build ni au modele lance."""
    def git(*args):
        r = subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True, timeout=60)
        if r.returncode:
            raise LaunchError(f"git {args[0]} : {r.stderr.strip() or r.returncode}")
        return r.stdout.strip()
    git("fetch", "--quiet")
    return {"current": git("log", "-1", "--format=%h du %cs"),
            "branch": git("rev-parse", "--abbrev-ref", "@{u}"),
            "behind": git("log", "--format=%h %cs %s", "HEAD..@{u}").splitlines()}


ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]|\r")


def tail(path, lines=150):
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - 128 * 1024))
            text = f.read().decode("utf-8", "replace")
    except FileNotFoundError:
        return ""
    return "\n".join(ANSI.sub("", text).splitlines()[-lines:])


# --- Bibliotheque (~/ia_models) : telechargements Hugging Face, liste, suppression ------

LIB = MODELS_DIR
META = ".ia_meta.json"  # ecrit a cote des fichiers telecharges : depot, commit, dates
HF_CLI = [str(ROOT / "venv-laya" / "bin" / "python"), "-m", "huggingface_hub.cli.hf"]
REPO = re.compile(r"[\w.-]+/[\w.-]+")
WEIGHTS = (".gguf", ".safetensors", ".ninfer", ".bin", ".pt", ".pth", ".onnx")
QUANT = re.compile(r"(?i)(?<![a-z0-9])(i?q\d(?:_[a-z0-9]+)*|p?t?q\d_\d|nvfp4|mxfp4|fp8|fp16|bf16|f16|f32|int[48]|awq|gptq|exl2|\d+(?:\.\d+)?bpw)(?![a-z0-9])")


def quant_of(name):
    m = QUANT.findall(name)
    return m[-1].upper() if m else None


def size_of(path):
    if path.is_file():
        return path.stat().st_size
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file() and not f.is_symlink())


def hf_token():
    tok = os.environ.get("HF_TOKEN")
    f = HOME / ".cache" / "huggingface" / "token"
    return tok or (f.read_text().strip() if f.exists() else None)


def hf_info(repo):
    if not REPO.fullmatch(repo):
        raise LaunchError("Dépôt attendu sous la forme organisation/nom.")
    req = urllib.request.Request(f"https://huggingface.co/api/models/{repo}?blobs=true")
    if hf_token():
        req.add_header("authorization", f"Bearer {hf_token()}")
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            d = json.load(r)
    except urllib.error.HTTPError as e:
        raise LaunchError({401: "Dépôt introuvable, ou privé / protégé (dans ce cas : « hf auth login » dans la WSL).",
                           404: "Dépôt introuvable."}.get(e.code, f"Hugging Face : erreur {e.code}"))
    base = (d.get("cardData") or {}).get("base_model")
    return {"repo": repo, "sha": d["sha"], "modified": d.get("lastModified"), "gated": bool(d.get("gated")),
            "tags": d.get("tags", [])[:10], "downloads": d.get("downloads"),
            "task": d.get("pipeline_tag"), "kind": TASK_KIND.get(d.get("pipeline_tag")),
            "base": (base[0] if isinstance(base, list) and base else base) or None,
            "files": [{"name": f["rfilename"], "size": f.get("size") or 0, "quant": quant_of(f["rfilename"])}
                      for f in d["siblings"]]}


# --- Est-ce que ca tourne sur cette machine ? -------------------------------------------
# Regles simples (pas de LLM : le verdict doit etre fiable et explicable).

SHARD = re.compile(r"-\d{5}-of-\d{5}")
FORMAT_ENGINE = {"gguf": "llama.cpp-prism", "ninfer": "ninfer"}  # safetensors : pas de moteur installe (vLLM...)
MIN_CC = {"NVFP4": 10.0, "MXFP4": 10.0, "FP8": 8.9}  # generation de GPU minimale pour ces formats


def hardware():
    gpu = query_gpu()
    base = LAUNCHER.baseline if LAUNCHER.baseline is not None else DEFAULT_BASELINE_MIB
    return {"gpu": gpu and gpu["name"], "cc": gpu and gpu["cc"],
            "vram_mib": gpu and gpu["total"], "vram_usable_mib": gpu and gpu["total"] - base,
            "vram_free_mib": gpu and gpu["total"] - gpu["used"],
            "ram_mib": round(psutil.virtual_memory().total / 2**20), "cpus": psutil.cpu_count(),
            "disk_free": shutil.disk_usage(LIB).free}


def installed(engine):
    e = ENGINES[engine]
    return not e.get("repo") or (Path(e["repo"]) / e["binary"]).exists()


def fit(size, fmt, quant, hw):
    """-> (verdict, explication). verdict : gpu | partial | no | incompatible | disk"""
    go = lambda mib: f"{mib / 1024:.1f}".replace(".", ",") + " Go"
    need = vram_estimate(size)
    engine = FORMAT_ENGINE.get(fmt)
    if not engine or not installed(engine):
        return "incompatible", f"Format {fmt} : aucun moteur installé pour le lancer (il faudrait vLLM ou transformers)."
    if quant in MIN_CC and (hw["cc"] or 0) < MIN_CC[quant]:
        return "incompatible", f"{quant} demande un GPU de génération {MIN_CC[quant]}+, le tien est en {hw['cc']}."
    if size > hw["disk_free"]:
        return "disk", f"Pas assez de place disque : {go(size / 2**20)} pour {go(hw['disk_free'] / 2**20)} libres."
    usable = hw["vram_usable_mib"] or 0
    if need <= usable:
        busy = " Il faudra d'abord arrêter ce qui occupe la VRAM." if need > (hw["vram_free_mib"] or 0) else ""
        return "gpu", f"Tient sur le GPU : ~{go(need)} nécessaires, {go(usable)} utilisables.{busy}"
    if fmt == "gguf" and need <= usable + hw["ram_mib"] * 0.7:
        return "partial", (f"Trop gros pour la VRAM (~{go(need)} pour {go(usable)}) : une partie tournera sur "
                           f"CPU/RAM, nettement plus lent.")
    return "no", f"Trop gros : ~{go(need)} nécessaires, {go(usable)} de VRAM" + (" + RAM." if fmt == "gguf" else ".")


def variants(repo, files, hw):
    """Regroupe les fichiers d'un depot en variantes lancables (1 GGUF decoupe = 1 variante)."""
    groups = {}
    has_st = any(f["name"].endswith(".safetensors") for f in files)
    for f in files:
        n = f["name"]
        if n.endswith(".gguf"):
            key, fmt = SHARD.sub("", n), "gguf"
        elif n.endswith(".ninfer"):
            key, fmt = n, "ninfer"
        elif n.endswith(".safetensors") or (not has_st and n.endswith((".bin", ".pt", ".pth"))):
            key, fmt = "Poids safetensors (dépôt complet)", "safetensors"
        else:
            continue
        groups.setdefault(key, {"name": key, "format": fmt, "files": []})["files"].append(f)
    out = []
    for v in groups.values():
        v["size"] = sum(f["size"] for f in v["files"])
        v["quant"] = quant_of(v["name"]) if v["format"] != "safetensors" else quant_of(repo)
        if v["format"] == "safetensors":  # + config / tokenizer, sinon le modele ne se charge pas
            v["files"] += [f for f in files if f["size"] < 50 * 2**20 and f["name"].endswith((".json", ".txt", ".model", ".jinja", ".py"))]
        if "mmproj" in v["name"].lower():
            v["verdict"], v["why"] = "extra", "Projecteur vision : optionnel, à télécharger avec le modèle pour les images."
        else:
            v["verdict"], v["why"] = fit(v["size"], v["format"], v["quant"], hw)
        v["files"] = [f["name"] for f in v["files"]]
        out.append(v)
    return sorted(out, key=lambda v: -v["size"])


def hf_check(repo):
    """Infos du depot + verdict par variante ; si rien ne tient sur le GPU, cherche d'autres depots
    quantifies du meme modele de base qui tiennent."""
    info, hw = hf_info(repo), hardware()
    info["hardware"] = hw
    info["variants"] = variants(repo, info["files"], hw)
    info["alternatives"] = []
    if any(v["verdict"] == "gpu" for v in info["variants"]):
        return info
    base = info["base"] or repo
    try:
        with urllib.request.urlopen(f"https://huggingface.co/api/models?filter=base_model:quantized:{base}"
                                    f"&filter=gguf&sort=downloads&direction=-1&limit=6", timeout=20) as r:
            # meme modele seulement : certains derives (finetunes) se declarent quantifies du meme base_model
            key = re.sub(r"[^a-z0-9]", "", base.split("/")[-1].lower())
            cands = [m["id"] for m in json.load(r) if m["id"] != repo and key in re.sub(r"[^a-z0-9]", "", m["id"].lower())]
    except Exception:
        return info

    def best(cand):
        try:
            ci = hf_info(cand)
        except Exception:
            return None
        ok = [v for v in variants(cand, ci["files"], hw) if v["verdict"] == "gpu"]
        # la plus grosse variante qui tient = la meilleure qualite
        return ok and {"repo": cand, "downloads": ci["downloads"], **max(ok, key=lambda v: v["size"])}
    with ThreadPoolExecutor(6) as ex:
        info["alternatives"] = [a for a in ex.map(best, cands) if a]
    info["base_searched"] = base
    return info


def lib_path(rel):
    """Chemin sous ~/ia_models venant de la page : refuse tout ce qui en sort."""
    p = (LIB / rel).resolve()
    hf = (LIB / "hf").resolve()
    if (p == LIB.resolve() or not p.is_relative_to(LIB.resolve()) or not p.exists()
            or (p.is_relative_to(hf) and not (p.parent == hf and p.name.startswith("models--")))):
        raise LaunchError("Chemin invalide.")
    return p


class Downloads:
    def __init__(self):
        self.lock = threading.Lock()
        self.jobs = {}  # n -> {repo, files, total, target, base, popen, state, msg}
        self.n = 0

    def start(self, repo, files):
        info = hf_info(repo)
        sizes = {f["name"]: f["size"] for f in info["files"]}
        if not files or any(f not in sizes for f in files):
            raise LaunchError("Choisis des fichiers du dépôt.")
        total = sum(sizes[f] for f in files)
        free = shutil.disk_usage(LIB).free
        if total > free - 5 * 2**30:
            raise LaunchError(f"Pas assez de place : {total / 2**30:.1f} Go à télécharger, {free / 2**30:.1f} Go libres.")
        target = LIB / repo.replace("/", "--")
        target.mkdir(parents=True, exist_ok=True)
        with self.lock:
            if any(j["target"] == target and j["state"] == "running" for j in self.jobs.values()):
                raise LaunchError("Un téléchargement de ce dépôt est déjà en cours.")
            self.n += 1
            n = self.n
            log = open(LOG_DIR / f"download-{n}.log", "w")
            popen = SPAWNER.submit(
                subprocess.Popen, [*HF_CLI, "download", repo, *files, "--revision", info["sha"],
                                   "--local-dir", str(target)],
                stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, start_new_session=True,
                preexec_fn=_die_with_launcher).result()
            log.close()
            self.jobs[n] = {"repo": repo, "files": files, "total": total, "target": target,
                            "base": size_of(target), "popen": popen, "state": "running", "msg": ""}
        threading.Thread(target=self._wait, args=(n, info), daemon=True).start()

    def _wait(self, n, info):
        j = self.jobs[n]
        code = j["popen"].wait()
        if j["state"] == "cancelled":
            return
        if code:
            j.update(state="error", msg=f"Échec (code {code}) : " + tail(LOG_DIR / f"download-{n}.log", 3))
            return
        meta_f = j["target"] / META
        meta = json.loads(meta_f.read_text()) if meta_f.exists() else {"files": {}}
        now = time.strftime("%Y-%m-%dT%H:%M:%S")
        meta.update(repo=info["repo"], sha=info["sha"], modified=info["modified"], task=info["task"])
        for f in j["files"]:
            meta["files"][f] = {"downloaded": now}
        meta_f.write_text(json.dumps(meta, indent=2))
        j["state"] = "done"

    def cancel(self, n):
        j = self.jobs.get(n)
        if j and j["state"] == "running":
            j["state"] = "cancelled"
            try:
                os.killpg(j["popen"].pid, signal.SIGTERM)
            except ProcessLookupError:
                pass

    def status(self):
        return [{"id": n, "repo": j["repo"], "files": j["files"], "total": j["total"], "state": j["state"],
                 "msg": j["msg"], "done": max(0, size_of(j["target"]) - j["base"]) if j["state"] == "running" else None}
                for n, j in sorted(self.jobs.items(), reverse=True)]


DOWNLOADS = Downloads()


def used_by(p):
    """Modeles de models.json dont le fichier est p ou dans p."""
    p = str(p.resolve())
    return sorted({m["name"] for m in MODELS.values()
                   for f in ([m["config"]["file"]] if m["config"].get("file") else [])
                   + [LIB / u for u in ENGINES[m["engine_id"]].get("uses", [])]
                   if str(Path(f).resolve()) == p or str(Path(f).resolve()).startswith(p + "/")})


def library():
    """Tout ce qui est dans ~/ia_models : depots telecharges d'ici, cache HF, fichiers poses a la main."""
    def date(ts):
        return time.strftime("%Y-%m-%d", time.localtime(ts))

    out = []
    for p in sorted(LIB.iterdir()):
        if p.name.startswith("."):
            continue
        if p.name == "hf":  # cache Hugging Face (Laya) : un depot par dossier models--org--nom
            for d in sorted(p.glob("models--*")):
                ref = d / "refs" / "main"
                # les snapshots sont des liens vers des blobs (parfois partages dans hf/blobs)
                snaps = [f for f in d.glob("snapshots/*/**/*") if f.is_file()]
                out.append({"path": str(d.relative_to(LIB)), "repo": d.name[8:].replace("--", "/"), "task": None,
                            "source": "cache HF", "sha": ref.read_text()[:7] if ref.exists() else None,
                            "size": sum(f.stat().st_size for f in {f.resolve() for f in snaps}),
                            "date": date(d.stat().st_mtime), "used_by": used_by(d),
                            "files": [{"name": "/".join(f.relative_to(d / "snapshots").parts[1:]),
                                       "quant": quant_of(f.name), "size": f.stat().st_size}
                                      for f in snaps if f.name.endswith(WEIGHTS)]})
            continue
        meta = json.loads((p / META).read_text()) if (p / META).exists() else None
        files = [p] if p.is_file() else [f for f in sorted(p.rglob("*"))
                                          if f.is_file() and f.name.endswith(WEIGHTS) and ".cache" not in f.parts]
        out.append({
            "path": p.name, "repo": meta and meta["repo"],
            "source": "Hugging Face" if meta else "local", "task": meta and meta.get("task"),
            "sha": meta and meta["sha"][:7], "hf_date": meta and (meta.get("modified") or "")[:10],
            "size": size_of(p), "date": date(p.stat().st_mtime), "used_by": used_by(p),
            "files": [{"name": str(f.relative_to(p)) if f != p else f.name, "quant": quant_of(f.name),
                       "size": f.stat().st_size, "path": str(f.relative_to(LIB)),
                       "downloaded": meta and meta["files"].get(str(f.relative_to(p)), {}).get("downloaded", "")[:10],
                       "used_by": used_by(f)} for f in files],
        })
    return {"dir": str(LIB), "free": shutil.disk_usage(LIB).free, "items": out, "downloads": DOWNLOADS.status(),
            "hardware": hardware()}


def lib_delete(rel):
    p = lib_path(rel)
    if used_by(p):
        raise LaunchError(f"Utilisé par {', '.join(used_by(p))} : retire d'abord ce modèle (ou change son fichier).")
    if any(j["state"] == "running" and (j["target"] == p or j["target"] in p.parents) for j in DOWNLOADS.jobs.values()):
        raise LaunchError("Téléchargement en cours : annule-le d'abord.")
    if p.parent == (LIB / "hf").resolve():  # cache HF : hf nettoie aussi les blobs partages
        r = subprocess.run([*HF_CLI, "cache", "rm", "model/" + p.name[8:].replace("--", "/"), "-y",
                            "--cache-dir", str(p.parent)], capture_output=True, text=True, timeout=120)
        if r.returncode:
            raise LaunchError("hf cache rm : " + (r.stderr or r.stdout).strip()[-300:])
    else:
        shutil.rmtree(p) if p.is_dir() else p.unlink()


# --- Launcher ---------------------------------------------------------------------

class Launcher:
    def __init__(self):
        self.lock = threading.RLock()
        self.runs = {}        # modeles lances d'ici : id -> {popen, started, vram_before, vram_load, opts}
        self.errors = {}      # id -> message
        self.stopping = set()
        self.updates = {}     # id -> {state: running|done|error, msg}
        self.baseline = None  # VRAM sans aucun modele
        self.pcache = {}      # pid -> psutil.Process (cpu_percent a besoin de l'historique)
        self.snapshot = {"ready": False}
        self.ip = lan_ip()
        LOG_DIR.mkdir(exist_ok=True)

    # -- boucle de mesure
    def run_forever(self):
        while True:
            try:
                self.poll()
            except Exception as e:  # la page doit continuer a repondre
                print("poll:", e, file=sys.stderr)
            time.sleep(POLL_S)

    def poll(self):
        gpu = query_gpu()
        procs = discover()
        if gpu and not gpu["pids"]:
            self.baseline = gpu["used"]
        base = self.baseline if self.baseline is not None else DEFAULT_BASELINE_MIB
        on_gpu = {mid: bool(gpu) and any(p.pid in gpu["pids"] for p in ps) for mid, ps in procs.items()}
        gpu_models = [mid for mid, v in on_gpu.items() if v]
        ncpu = psutil.cpu_count() or 1
        out = {}
        with self.lock:
            for mid, m in MODELS.items():
                ps = procs.get(mid, [])
                run = self.runs.get(mid)
                if run and run["popen"].poll() is not None and mid not in self.stopping and not ps:
                    self.errors[mid] = f"Arrêté tout seul (code {run['popen'].returncode}) : voir les logs."
                    self.runs.pop(mid)
                    run = None
                healthy = bool(ps) and http_ok(m["port"], m["health"])
                if mid in self.stopping:
                    state = "stopping"
                elif not ps:
                    state = "error" if mid in self.errors else "stopped"
                elif healthy:
                    state = "ready"
                else:
                    state = "starting"
                if state == "ready" and run and run["vram_load"] is None and gpu and run["vram_before"] is not None:
                    run["vram_load"] = max(0, gpu["used"] - run["vram_before"])

                vram, vram_how = None, None
                if ps and gpu:
                    if not on_gpu[mid]:
                        vram, vram_how = 0, "cpu"
                    elif gpu_models == [mid]:
                        vram = max(0, gpu["used"] - base)
                        vram_how = "live" if self.baseline is not None else "estimate"
                    elif run and run["vram_load"] is not None:
                        vram, vram_how = run["vram_load"], "load"
                    else:
                        vram_how = "shared"

                rss, cpu, started = 0, 0.0, None
                for p in ps:
                    cp = self.pcache.setdefault(p.pid, p)
                    try:
                        with cp.oneshot():
                            rss += cp.memory_info().rss
                            cpu += cp.cpu_percent(None)
                            ct = cp.create_time()
                            started = ct if started is None else min(started, ct)
                    except psutil.Error:
                        pass

                out[mid] = {
                    "state": state,
                    "managed": run is not None,
                    "error": self.errors.get(mid),
                    "pids": [p.pid for p in ps],
                    "on_gpu": on_gpu[mid],
                    "vram_mib": vram,
                    "vram_how": vram_how,
                    "rss_mib": round(rss / 2**20) if ps else None,
                    "cpu_pct": round(cpu, 1) if ps else None,        # 100 = un coeur
                    "cpu_machine_pct": round(cpu / ncpu, 1) if ps else None,
                    "uptime_s": round(time.time() - started) if started else None,
                    "opts": run["opts"] if run else None,
                    "update": self.updates.get(mid) and {
                        **self.updates[mid], "log": tail(LOG_DIR / f"{mid}-update.log", 20)},
                }
            alive = {p.pid for ps in procs.values() for p in ps}
            self.pcache = {pid: p for pid, p in self.pcache.items() if pid in alive}

        vm = psutil.virtual_memory()
        self.snapshot = {
            "ready": True,
            "time": time.time(),
            "lan_ip": self.ip,
            "gpu": None if not gpu else {k: v for k, v in gpu.items() if k != "pids"} | {
                "baseline": base, "baseline_measured": self.baseline is not None},
            "ram": {"used_mib": round((vm.total - vm.available) / 2**20), "total_mib": round(vm.total / 2**20)},
            "cpu": {"pct": psutil.cpu_percent(None), "count": ncpu},
            "models": out,
        }

    # -- actions
    def start(self, mid, opts):
        m = MODELS[mid]
        with self.lock:
            if discover().get(mid):
                raise LaunchError("Déjà lancé.")
            for port, who in m["conflicts"].items():
                if port_open(port):
                    raise LaunchError(f"{who} tourne (port {port}) : arrête-le d'abord.")
            if port_open(m["port"]):
                raise LaunchError(f"Le port {m['port']} est déjà occupé par un autre programme.")
            clean = {}
            for o in m["options"]:
                v = str(opts.get(o["key"], o["default"]))
                clean[o["key"]] = v if v in [c[0] for c in o["choices"]] else o["default"]
            gpu = query_gpu()
            cmd, env, vram_needed = ENGINES[m["engine_id"]]["run"](m["config"], m["fixed"] | clean, gpu)
            if gpu and vram_needed:
                free = gpu["total"] - gpu["used"]
                if free < vram_needed:
                    others = [MODELS[o]["name"] for o, s in self.snapshot.get("models", {}).items()
                              if o != mid and s.get("on_gpu")]
                    hint = f" ({', '.join(others)} l'occupe : arrête-le, ou choisis le CPU)" if others else ""
                    raise LaunchError(f"Pas assez de VRAM libre : {free / 1024:.1f} Go, il en faut ~"
                                      f"{vram_needed / 1024:.0f} Go{hint}.")
            log = open(LOG_DIR / f"{mid}.log", "w")
            log.write(f"$ {' '.join(cmd)}\n  {' '.join(f'{k}={v}' for k, v in env.items())}\n\n")
            log.flush()
            popen = SPAWNER.submit(
                subprocess.Popen, cmd, env={**os.environ, **env}, cwd=ROOT, stdin=subprocess.DEVNULL,
                stdout=log, stderr=subprocess.STDOUT, start_new_session=True,
                preexec_fn=_die_with_launcher).result()
            log.close()
            self.runs[mid] = {"popen": popen, "started": time.time(), "opts": clean,
                              "vram_before": gpu["used"] if gpu else None, "vram_load": None}
            self.errors.pop(mid, None)

    def stop(self, mid):
        with self.lock:
            procs = discover().get(mid, [])
            self.errors.pop(mid, None)
            if not procs:
                self.runs.pop(mid, None)
                return
            self.stopping.add(mid)
        threading.Thread(target=self._kill, args=(mid, procs), daemon=True).start()

    def _kill(self, mid, procs):
        run = self.runs.get(mid)
        try:
            if run:
                # tout le groupe : le watchdog de start-ninfer.sh et son "sleep"
                try:
                    os.killpg(run["popen"].pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
            for p in procs:
                try:
                    p.terminate()
                except psutil.Error:
                    pass
            _, alive = psutil.wait_procs(procs, timeout=20)
            for p in alive:
                try:
                    p.kill()
                except psutil.Error:
                    pass
            if run:
                try:
                    run["popen"].wait(5)
                except subprocess.TimeoutExpired:
                    pass
        finally:
            with self.lock:
                self.runs.pop(mid, None)
                self.stopping.discard(mid)

    def update(self, mid):
        with self.lock:
            if self.updates.get(mid, {}).get("state") == "running":
                raise LaunchError("Mise à jour déjà en cours.")
            self.updates[mid] = {"state": "running", "msg": "git pull…"}
        threading.Thread(target=self._update, args=(mid, MODELS[mid]), daemon=True).start()

    def _update(self, mid, m):
        """pull + build pendant que le modele tourne : le processus lance garde l'ancien
        binaire (le linker cree un nouveau fichier). Echec du build -> retour au commit
        et au binaire d'avant."""
        u = self.updates[mid]
        repo = Path(m["repo"])
        binary = repo / m["binary"]
        prev = binary.with_name(binary.name + ".prev")
        with open(LOG_DIR / f"{mid}-update.log", "w") as log:
            def sh(*cmd):
                log.write(f"\n$ {' '.join(cmd)}\n")
                log.flush()
                return subprocess.run(cmd, cwd=repo, stdin=subprocess.DEVNULL, stdout=log,
                                      stderr=subprocess.STDOUT).returncode == 0

            def git(*args):
                return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True).stdout.strip()
            try:
                if git("status", "--porcelain", "--untracked-files=no"):
                    u.update(state="error", msg="Modifications locales dans le dépôt : mise à jour annulée.")
                    return
                old = git("rev-parse", "--short", "HEAD")
                if not sh("git", "merge", "--ff-only", "@{u}"):
                    u.update(state="error", msg="git pull impossible (branche divergente ?) : voir le log.")
                    return
                new = git("rev-parse", "--short", "HEAD")
                shutil.copy2(binary, prev)
                u["msg"] = f"compilation {old} → {new}… (le modèle lancé n'est pas touché)"
                if sh("nice", "-n", "19", *m["build"]):
                    u.update(state="done", msg=f"Compilé ({old} → {new}). Arrête / redémarre le modèle pour l'utiliser.")
                else:
                    sh("git", "reset", "--hard", old)
                    os.replace(prev, binary)
                    u.update(state="error", msg=f"Compilation échouée : retour à {old}, ancien binaire conservé. Voir le log.")
            except Exception as e:
                log.write(f"\n{type(e).__name__}: {e}\n")
                u.update(state="error", msg=f"{type(e).__name__}: {e}")

    def shutdown(self):
        with self.lock:
            mine = [mid for mid in self.runs]
        for mid in mine:
            procs = discover().get(mid, [])
            if procs:
                print(f"arret de {mid}...", flush=True)
                self.stopping.add(mid)
                self._kill(mid, procs)



LAUNCHER = Launcher()


# --- HTTP -------------------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    server_version = "ia-launcher"

    def log_message(self, fmt, *args):
        pass

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code)
        self.send_header("content-type", ctype)
        self.send_header("content-length", str(len(data)))
        self.send_header("cache-control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _body(self):
        n = int(self.headers.get("content-length") or 0)
        if n > 1 << 20:
            raise LaunchError("Requete trop grosse.")
        return json.loads(self.rfile.read(n) or b"{}")

    def do_GET(self):
        if self.path in ("/", "/index.html", "/modeles"):  # /modeles : meme page, vue gestion des modeles
            return self._send(200, (ROOT / "index.html").read_bytes(), "text/html; charset=utf-8")
        if self.path == "/api/status":
            return self._send(200, LAUNCHER.snapshot)
        if self.path == "/api/models":
            return self._send(200, {
                "models": MODELS, "kinds": KINDS, "task_kind": TASK_KIND,
                "engines": {k: {"label": e["label"], "params": e["params"], "needs_file": e["needs_file"]}
                            for k, e in ENGINES.items()}})
        if self.path == "/api/library":
            return self._send(200, library())
        m = re.fullmatch(r"/api/logs/(\w+)", self.path)
        if m and m.group(1) in MODELS:
            mid = m.group(1)
            if LAUNCHER.runs.get(mid) or (LOG_DIR / f"{mid}.log").exists():
                text = tail(LOG_DIR / f"{mid}.log")
            else:
                text = ""
            return self._send(200, {"log": text})
        self._send(404, {"error": "introuvable"})

    def do_POST(self):
        # page servie sur le LAN : on refuse les POST venus d'un autre site (origine != hote demande)
        origin = self.headers.get("origin")
        if origin and origin != f"http://{self.headers.get('host')}":
            return self._send(403, {"error": "origine refusee"})
        try:
            m = re.fullmatch(r"/api/(check|update)/(\w+)", self.path)
            if m and MODELS.get(m.group(2), {}).get("repo"):
                if m.group(1) == "check":
                    return self._send(200, check_update(MODELS[m.group(2)]["repo"]))
                LAUNCHER.update(m.group(2))
                LAUNCHER.poll()
                return self._send(200, {"ok": True})
            m = re.fullmatch(r"/api/model/(\w+)(/delete)?", self.path)
            if m:
                mid, body = m.group(1), self._body()
                not_running(mid)
                if m.group(2):
                    edit_config(lambda cfg: cfg.pop(mid, None))
                else:
                    # les champs absents du formulaire (extra_args, conflicts...) sont gardes
                    edit_config(lambda cfg: cfg.__setitem__(mid, {**cfg.get(mid, {}), **body}))
                return self._send(200, {"ok": True})
            m = re.fullmatch(r"/api/profile/(\w+)", self.path)
            if m and m.group(1) in CFG:
                mid, body = m.group(1), self._body()
                name = str(body.get("name", "")).strip()[:80]
                if not name:
                    raise LaunchError("Nom de profil vide.")

                def set_profile(cfg):
                    profs = cfg[mid].setdefault("profiles", {})
                    if body.get("opts") is None:
                        profs.pop(name, None)
                    else:
                        profs[name] = {str(k): str(v) for k, v in body["opts"].items()}
                edit_config(set_profile)
                return self._send(200, {"ok": True})
            if self.path == "/api/hf/info":
                return self._send(200, hf_check(str(self._body().get("repo", "")).strip()))
            if self.path == "/api/hf/download":
                b = self._body()
                DOWNLOADS.start(str(b.get("repo", "")), [str(f) for f in b.get("files", [])])
                return self._send(200, {"ok": True})
            m = re.fullmatch(r"/api/hf/cancel/(\d+)", self.path)
            if m:
                DOWNLOADS.cancel(int(m.group(1)))
                return self._send(200, {"ok": True})
            if self.path == "/api/library/delete":
                lib_delete(str(self._body().get("path", "")))
                return self._send(200, {"ok": True})
            if self.path == "/api/reload":
                reload_config()
                return self._send(200, {"ok": True})
            m = re.fullmatch(r"/api/(start|stop)/(\w+)", self.path)
            if m and m.group(2) in MODELS:
                if m.group(1) == "start":
                    LAUNCHER.start(m.group(2), self._body())
                else:
                    LAUNCHER.stop(m.group(2))
                LAUNCHER.poll()
                return self._send(200, {"ok": True})
            self._send(404, {"error": "introuvable"})
        except LaunchError as e:
            self._send(409, {"error": str(e)})
        except Exception as e:
            self._send(500, {"error": f"{type(e).__name__}: {e}"})


def main():
    server = ThreadingHTTPServer((LISTEN_HOST, LISTEN_PORT), Handler)
    server.daemon_threads = True

    def bye(*_):
        LAUNCHER.shutdown()
        os._exit(0)

    for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        signal.signal(sig, bye)
    LAUNCHER.poll()
    threading.Thread(target=LAUNCHER.run_forever, daemon=True).start()
    print(f"IA Launcher : http://{LISTEN_HOST}:{LISTEN_PORT}   (Ctrl+C pour arreter)", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
