"""One-off check: what the launcher answers for Qwen3-TTS (catalog suggestion included)."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hominfer.config import CATALOG_DIR
from hominfer.domain import compat
from hominfer.i18n import set_lang
from hominfer.infra import huggingface as hf
from hominfer.services.catalog import Catalog

set_lang("en")
class Reg:  # minimal registry stub: no engine configured, nothing installed
    engines = {}
    installed = staticmethod(lambda eid: False)

catalog = Catalog(CATALOG_DIR, registry=Reg(), log_dir=Path("/tmp"), models_dir=lambda: Path.home())
hw = {"cc": 12.0, "vram_usable_mib": 30000, "vram_free_mib": 30000, "ram_mib": 48000, "disk_free": 900 * 2**30}
engines = {}
ctx = compat.Context(engines=engines, hw=hw, installed=lambda eid: False, lib_has=lambda rel: True,
                     suggest=lambda fmt, kind, repo: catalog.suggest(fmt, kind, repo, hw["cc"]))
info = hf.model_info("Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice")
print("task:", info["task"])
for v in compat.variants(info["repo"], info["files"], "tts", ctx):
    print(json.dumps({k: v.get(k) for k in ("name", "verdict", "why", "suggest")}, indent=1))
