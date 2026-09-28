#!/usr/bin/env python3
"""IA Launcher: web page to start / stop local AI models and see their VRAM / RAM / CPU.
Models (models.json) run on engines (engines.json): nothing model- or engine-specific in the code.

    just run   (ou service systemd : just install-service)   ->  http://<ip-lan>:8090 (ecoute sur 0.0.0.0)

Les modeles lances d'ici sont arretes quand le launcher s'arrete (just restart aussi).
Un moteur lance hors du launcher est detecte (par ses noms de processus) et peut etre arrete.

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


# --- Engines (engines.json) ---------------------------------------------------------
# An engine = how to run one kind of model: command, env, health check, params. They are
# declared in engines.json (local, edited by hand only): the page, reachable from the LAN,
# can pick one of them for a model but never write a command. See engines.example.json.
# Placeholders in command / env: {port} {file} {file_name} {file_dir} {models_dir} {model_id}
# and every param ({ctx}...). Optional param: an env var or argument that ends up empty is
# dropped, and so is a group of arguments (a list inside command) with any empty placeholder.

ENGINES_FILE = ROOT / "engines.json"
PLACEHOLDER = re.compile(r"\{(\w+)\}")
BUILTIN_VARS = {"port", "file", "file_name", "file_dir", "models_dir", "model_id"}
# a model uses its "auto" device on GPU only if this much VRAM stays free on top of its own
AUTO_DEVICE_MARGIN_MIB = 1536


def expand(s):
    return str(HOME / s[2:]) if isinstance(s, str) and s.startswith("~/") else s


def flat(command):
    return [x for a in command for x in (a if isinstance(a, list) else [a])]


def check_engine(eid, e):
    def need(cond, msg):
        if not cond:
            raise LaunchError(f"engines.json : {eid} : {msg}")
    need(re.fullmatch(r"[\w.-]+", eid), "identifiant : lettres, chiffres, . _ - uniquement")
    need(isinstance(e.get("label"), str) and e["label"], "label manquant")
    need(isinstance(e.get("command"), list) and e["command"] and isinstance(e["command"][0], str)
         and all(isinstance(a, str) or isinstance(a, list) and all(isinstance(x, str) for x in a) for a in e["command"]),
         "command : liste de chaînes (ou de groupes optionnels [\"--opt\", \"{param}\"])")
    need(isinstance(e.get("env", {}), dict) and all(isinstance(v, str) for v in e.get("env", {}).values()),
         "env : valeurs en chaînes")
    need(isinstance(e.get("procs"), list) and e["procs"], "procs : noms des processus du moteur (argv[0] / argv[1])")
    for k in ("health", "endpoint"):
        need(str(e.get(k, "")).startswith("/"), f"{k} : chemin HTTP commençant par /")
    params = e.get("params", {})
    need(isinstance(params, dict) and all(WORD.fullmatch(k) for k in params), "params : clés en lettres / chiffres")
    need(e.get("device_param") in (None, *params), "device_param : doit être un des params")
    for arg in [*flat(e["command"]), *e.get("env", {}).values()]:
        for var in PLACEHOLDER.findall(arg):
            need(var in BUILTIN_VARS or var in params, f"{{{var}}} : ni un param ni {', '.join(sorted(BUILTIN_VARS))}")


def load_engines():
    if not ENGINES_FILE.exists():
        raise LaunchError("engines.json introuvable : copie engines.example.json et adapte-le.")
    engines = json.loads(ENGINES_FILE.read_text())
    for eid, e in engines.items():
        check_engine(eid, e)
        e["params"] = {k: v if isinstance(v, dict) else {"label": v} for k, v in e.get("params", {}).items()}
        e["file_ext"] = e.get("file_ext", [])
        e["needs_file"] = bool(e["file_ext"])
        if e.get("repo"):
            e["repo"] = expand(e["repo"])
    return engines


def engine_run(mid, m, p, gpu):
    """models.json entry + chosen params -> (argv, env, VRAM to reserve before starting)."""
    e = ENGINES[m["engine"]]
    p = {k: spec.get("default", "") for k, spec in e["params"].items()} | p
    need = vram_need(m)
    dev = e.get("device_param")
    if dev:
        if p[dev] == "auto":
            free = gpu["total"] - gpu["used"] if gpu else 0
            p[dev] = "cuda" if free >= need + AUTO_DEVICE_MARGIN_MIB else "cpu"
        if p[dev] == "cpu":
            need = 0
    values = {k: str(spec.get("map", {}).get(p[k], p[k])) for k, spec in e["params"].items()}
    f = Path(m["file"]) if m.get("file") else None
    values |= {"port": str(m["port"]), "models_dir": str(MODELS_DIR), "file": str(f or ""), "model_id": mid,
               "file_name": f.name if f else "", "file_dir": str(f.parent) if f else ""}

    def sub(s):
        return PLACEHOLDER.sub(lambda mm: values[mm.group(1)], expand(s))

    def empty(s):
        return any(not values[v] for v in PLACEHOLDER.findall(s))
    cmd = []
    for a in e["command"]:
        if isinstance(a, list):
            if not any(empty(x) for x in a):
                cmd += [sub(x) for x in a]
        elif sub(a):
            cmd.append(sub(a))
    cmd += [str(a) for a in m.get("extra_args", [])]
    env = {k: v for k, v in ((k, sub(v)) for k, v in e.get("env", {}).items()) if v}
    return cmd, env, need


def vram_estimate(size):
    # ponytail: poids +10 % + 1 Go (KV a contexte moyen, runtime) ; mesurer et fixer vram_mib si un gros contexte deborde
    return round(size / 2**20 * 1.1 + 1024)


def vram_need(c):
    """VRAM demandee avant lancement (seulement un garde-fou : le moteur prend ce qu'il lui faut).
    vram_mib dans models.json si mesure a la main, sinon estimee depuis la taille du fichier."""
    if c.get("vram_mib"):
        return c["vram_mib"]
    f = Path(c.get("file") or "/nonexistent")
    if not f.is_file():
        return 0
    if ENGINES.get(c.get("engine"), {}).get("loads_dir"):  # the engine loads every shard of the folder
        return vram_estimate(sum(x.stat().st_size for x in f.parent.glob(f"*{f.suffix}")))
    return vram_estimate(f.stat().st_size)


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
        need(Path(c["file"]).suffix in e["file_ext"], f"{e['label']} lance des {' / '.join(e['file_ext'])}")
    need(isinstance(c.get("extra_args", []), list)
         and all(isinstance(a, str) and re.fullmatch(r"[\w.:/+=,@-]{1,300}", a) for a in c.get("extra_args", [])),
         "extra_args : liste d'arguments (lettres, chiffres, . : / + = , @ -)")
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
    cfg = json.loads(CONFIG.read_text()) if CONFIG.exists() else {}  # models.json: local, not in git
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


ENGINES = load_engines()
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
            # engines loading the model folder (vLLM) get the file's directory in argv
            if names & set(m["procs"]) and (not m["match"] or m["match"] in cmd or str(Path(m["match"]).parent) in cmd):
                found[mid].append(p)
                break
    # + their children (e.g. vLLM's EngineCore, which holds the GPU memory)
    for mid, ps in found.items():
        seen = {p.pid for p in ps}
        for p in list(ps):
            try:
                ps += [c for c in p.children(recursive=True) if c.pid not in seen and not seen.add(c.pid)]
            except psutil.Error:
                pass
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
HF_CLI = [sys.executable, "-m", "huggingface_hub.cli.hf"]  # huggingface_hub: requirements.txt
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
MIN_CC = {"NVFP4": 10.0, "MXFP4": 10.0, "FP8": 8.9}  # generation de GPU minimale pour ces formats


def hardware():
    gpu = query_gpu()
    base = LAUNCHER.baseline if LAUNCHER.baseline is not None else DEFAULT_BASELINE_MIB
    return {"gpu": gpu and gpu["name"], "cc": gpu and gpu["cc"],
            "vram_mib": gpu and gpu["total"], "vram_usable_mib": gpu and gpu["total"] - base,
            "vram_free_mib": gpu and gpu["total"] - gpu["used"],
            "ram_mib": round(psutil.virtual_memory().total / 2**20), "cpus": psutil.cpu_count(),
            "disk_free": shutil.disk_usage(LIB).free}


def installed(eid):
    return engine_present(ENGINES[eid])


def engine_present(e):
    """Engine's executable (and script given as first argument, e.g. bash /path/start.sh) present."""
    exe = expand(e["command"][0])
    arg = expand(e["command"][1]) if len(e["command"]) > 1 and isinstance(e["command"][1], str) else ""
    ok = Path(exe).exists() if "/" in exe else shutil.which(exe)
    ok = ok and (not arg.startswith("/") or "{" in arg or Path(arg).exists())
    return bool(ok) and (not e.get("binary") or (Path(expand(e["repo"])) / e["binary"]).exists())


def fit(size, fmt, quant, hw, repo=None, kind=None):
    """-> (verdict, explication). verdict : installed | gpu | partial | no | incompatible | disk"""
    go = lambda mib: f"{mib / 1024:.1f}".replace(".", ",") + " Go"
    need = vram_estimate(size)
    # engines that fetch their own weights (e.g. a server reading the HF cache)
    for e in ENGINES.values():
        if repo in e.get("provides_repos", []):
            if all((LIB / u).exists() for u in e.get("uses", [])):
                return "installed", f"Déjà installé : {e['label']} charge ce modèle lui-même. Rien à télécharger."
            return "incompatible", (f"{e['label']} télécharge ce modèle lui-même"
                                    + (f" : {e['install_hint']}" if e.get("install_hint") else "") + ".")
    engines = [eid for eid, e in ENGINES.items() if f".{fmt}" in e["file_ext"]]
    if not engines:
        return "incompatible", f"Format {fmt} : aucun moteur de engines.json ne lance ce format."
    fitting = [eid for eid in engines if kind is None or kind in ENGINES[eid].get("kinds", [kind])]
    if not fitting:
        labels = ", ".join(ENGINES[eid]["label"] for eid in engines)
        return "incompatible", f"Modèle de type {KINDS.get(kind, kind)} : {labels} ne lance pas ce genre de modèle."
    if not any(installed(eid) for eid in fitting):
        return "incompatible", f"Format {fmt} : {ENGINES[fitting[0]]['label']} est déclaré mais pas installé."
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


def variants(repo, files, hw, kind=None):
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
            v["verdict"], v["why"] = fit(v["size"], v["format"], v["quant"], hw, repo, kind)
            if v["verdict"] == "incompatible":
                v["suggest"] = suggest_engine(v["format"], kind, repo, hw)
        v["files"] = [f["name"] for f in v["files"]]
        out.append(v)
    return sorted(out, key=lambda v: -v["size"])


def hf_check(repo):
    """Infos du depot + verdict par variante ; si c'est un LLM trop gros pour le GPU, cherche
    d'autres depots quantifies du meme modele de base qui tiennent."""
    info, hw = hf_info(repo), hardware()
    info["hardware"] = hw
    info["variants"] = variants(repo, info["files"], hw, info["kind"])
    info["alternatives"] = []
    # les versions GGUF d'un autre depot ne valent que pour un LLM : un GGUF de modele de
    # decision / TTS... ne se lance pas avec llama-server
    if any(v["verdict"] in ("gpu", "installed") for v in info["variants"]) or info["kind"] not in (None, "llm"):
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
        ok = [v for v in variants(cand, ci["files"], hw, ci["kind"]) if v["verdict"] == "gpu"]
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
        if p.name == "hf":  # Hugging Face cache (engines that fetch their own weights): one repo per models--org--name
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


# --- Engine catalog (catalog/) ------------------------------------------------------------
# Known engines, versioned with the launcher: what each one runs, and a script installing it
# in ~/llm/<engine> (idempotent: running it again updates / reconfigures). The page can only
# pick a catalog id; once installed, the engine's block is added to engines.json if its id is free.

CATALOG_DIR = ROOT / "catalog"
CATALOG = json.loads((CATALOG_DIR / "catalog.json").read_text())


def catalog_state(cid):
    """configured: in engines.json and present | present: on disk (maybe partly), not configured | available"""
    c = CATALOG[cid]
    if cid in ENGINES and installed(cid):
        return "configured"
    found = engine_present(c["engine"]) or c.get("detect") and (Path(expand(c["dir"])) / c["detect"]).exists()
    return "present" if found else "available"


def catalog_compat(cid, hw_cc):
    need = CATALOG[cid].get("min_cc")
    if need and (hw_cc or 0) < need:
        return False, f"Demande un GPU de génération {need}+, le tien est en {hw_cc}."
    return True, ""


def suggest_engine(fmt, kind, repo, hw):
    """Catalog engine that would run this variant, if it isn't set up yet."""
    for cid, c in CATALOG.items():
        e = c["engine"]
        runs = repo in e.get("provides_repos", []) or (
            f".{fmt}" in e.get("file_ext", []) and (kind is None or kind in e.get("kinds", [kind])))
        if runs and catalog_state(cid) != "configured" and catalog_compat(cid, hw["cc"])[0]:
            return {"id": cid, "label": c["label"], "disk_gb": c["disk_gb"], "minutes": c["minutes"],
                    "state": catalog_state(cid)}
    return None


def compact_json(v, ind=0, lead=0, width=110):
    """JSON as written by hand: a value on one line when it fits, else one entry per line."""
    one = json.dumps(v, ensure_ascii=False)
    if not isinstance(v, (dict, list)) or not v or ind + lead + len(one) <= width:
        return one
    pad = " " * (ind + 2)
    if isinstance(v, dict):
        rows = [f"{pad}{json.dumps(k, ensure_ascii=False)}: {compact_json(x, ind + 2, len(k) + 4, width)}"
                for k, x in v.items()]
        return "{\n" + ",\n".join(rows) + "\n" + " " * ind + "}"
    if all(not isinstance(x, (dict, list)) for x in v):  # plain values: fill each line up to the width
        lines, cur = [], ""
        for x in (json.dumps(x, ensure_ascii=False) for x in v):
            if cur and ind + 2 + len(cur) + len(x) + 2 > width:
                lines.append(cur)
                cur = ""
            cur += (", " if cur else "") + x
        return "[\n" + ",\n".join(pad + line for line in lines + [cur]) + "\n" + " " * ind + "]"
    return "[\n" + ",\n".join(pad + compact_json(x, ind + 2, 0, width) for x in v) + "\n" + " " * ind + "]"


def save_engines(raw):
    tmp = ENGINES_FILE.with_suffix(".tmp")
    tmp.write_text(compact_json(raw) + "\n")
    os.replace(tmp, ENGINES_FILE)


class Installs:
    def __init__(self):
        self.lock = threading.Lock()
        self.jobs = {}  # catalog id -> {state: running|done|error, msg, popen}

    def start(self, cid):
        if cid not in CATALOG:
            raise LaunchError("Moteur inconnu du catalogue.")
        gpu = query_gpu()
        ok, why = catalog_compat(cid, gpu and gpu["cc"])
        if not ok:
            raise LaunchError(why)
        c = CATALOG[cid]
        with self.lock:
            if self.jobs.get(cid, {}).get("state") == "running":
                raise LaunchError("Installation déjà en cours.")
            log = open(LOG_DIR / f"engine-{cid}.log", "w")
            env = {**os.environ, "INSTALL_DIR": expand(c["dir"]), "GPU_CC": str(gpu["cc"]) if gpu else ""}
            popen = SPAWNER.submit(
                subprocess.Popen, ["bash", str(CATALOG_DIR / c["script"])], env=env, cwd=CATALOG_DIR,
                stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, start_new_session=True,
                preexec_fn=_die_with_launcher).result()
            log.close()
            self.jobs[cid] = {"state": "running", "msg": f"Installation dans {c['dir']}…", "popen": popen}
        threading.Thread(target=self._wait, args=(cid,), daemon=True).start()

    def _wait(self, cid):
        j = self.jobs[cid]
        code = j["popen"].wait()
        if code:
            j.update(state="error", msg=f"Échec (code {code}) : voir le log.")
            return
        try:
            j.update(state="done", msg=self.register(cid))
        except Exception as e:
            j.update(state="error", msg=f"Installé, mais engines.json non mis à jour : {e}")

    @staticmethod
    def register(cid):
        global ENGINES
        with CONFIG_LOCK:
            raw = json.loads(ENGINES_FILE.read_text()) if ENGINES_FILE.exists() else {}
            if cid in raw:
                return f"Installé. « {cid} » était déjà dans engines.json : laissé tel quel."
            raw[cid] = CATALOG[cid]["engine"]
            check_engine(cid, json.loads(json.dumps(raw[cid])))
            save_engines(raw)
            ENGINES = load_engines()
        return "Installé et ajouté à engines.json : il est proposé dans le formulaire des modèles."

    def status(self, hw_cc):
        out = []
        for cid, c in CATALOG.items():
            e, j = c["engine"], self.jobs.get(cid)
            ok, why = catalog_compat(cid, hw_cc)
            out.append({"id": cid, "label": c["label"], "desc": c["desc"], "url": c["url"], "dir": c["dir"],
                        "disk_gb": c["disk_gb"], "minutes": c["minutes"], "kinds": e.get("kinds", []),
                        "file_ext": e.get("file_ext", []), "state": catalog_state(cid),
                        "compatible": ok, "why": why,
                        "job": j and {"state": j["state"], "msg": j["msg"],
                                      "log": tail(LOG_DIR / f"engine-{cid}.log", 40)}})
        return out


INSTALLS = Installs()


# --- Launcher ---------------------------------------------------------------------

# ES_CONTINUOUS | ES_SYSTEM_REQUIRED until stdin closes (the screen may still turn off).
# None outside WSL or with interop disabled: no sleep blocking.
POWERSHELL = shutil.which("powershell.exe", path=os.environ.get("PATH", "") + ":/mnt/c/Windows/System32/WindowsPowerShell/v1.0")  # systemd: no Windows PATH
NO_SLEEP_PS = r'''Add-Type -Namespace W -Name P -MemberDefinition '[DllImport("kernel32.dll")] public static extern uint SetThreadExecutionState(uint f);'
[void][W.P]::SetThreadExecutionState([uint32]"0x80000001")
[void][Console]::In.ReadLine()'''


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
        self.awake = None     # PowerShell process holding off Windows sleep
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
        self.keep_awake(any(o["pids"] for o in out.values()))

    # -- Windows sleep: blocked while a model is loaded
    def keep_awake(self, on):
        if not POWERSHELL or on == (self.awake is not None and self.awake.poll() is None):
            return
        if on:  # released when the process ends, including when the launcher dies (stdin closes)
            self.awake = subprocess.Popen([POWERSHELL, "-NoProfile", "-NonInteractive", "-Command", NO_SLEEP_PS],
                                          stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            self.awake.stdin.close()  # EOF -> the PowerShell process exits and Windows may sleep again
            self.awake = None

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
            cmd, env, vram_needed = engine_run(mid, m["config"], m["fixed"] | clean, gpu)
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
                "engines": {k: {"label": e["label"], "params": e["params"], "needs_file": e["needs_file"],
                                "file_ext": e["file_ext"], "kinds": e.get("kinds"), "installed": installed(k)}
                            for k, e in ENGINES.items()}})
        if self.path == "/api/library":
            return self._send(200, library())
        if self.path == "/api/engines":
            gpu = query_gpu()
            return self._send(200, {"catalog": INSTALLS.status(gpu and gpu["cc"]),
                                    "configured": {k: {"label": e["label"], "installed": installed(k)}
                                                   for k, e in ENGINES.items()}})
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
            m = re.fullmatch(r"/api/engines/install/([\w.-]+)", self.path)
            if m:
                INSTALLS.start(m.group(1))
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
