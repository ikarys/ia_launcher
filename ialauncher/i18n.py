"""Texts in the UI language: locales/<lang>.json, same keys for the page and the server.

The current language is process-wide (one launcher serves one household / LAN), set by the
settings service.
"""
import json
import re

from . import config

LOCALES = {p.stem: json.loads(p.read_text()) for p in sorted(config.LOCALES_DIR.glob("*.json"))}
DEFAULT_LANG = "en"
_VAR = re.compile(r"\{(\w+)\}")
_current = {"lang": DEFAULT_LANG}


def set_lang(lang):
    _current["lang"] = lang if lang in LOCALES else DEFAULT_LANG


def lang():
    return _current["lang"]


def tr(key, /, **kw):
    """Text in the UI language (English when missing); {name} replaced by kw, others kept."""
    s = LOCALES.get(lang(), {}).get(key) or LOCALES.get(DEFAULT_LANG, {}).get(key, key)
    return _VAR.sub(lambda m: str(kw[m.group(1)]) if m.group(1) in kw else m.group(0), s)


def loc(value):
    """Text from a config file: a plain string, or {"en": "...", "fr": "..."}."""
    if isinstance(value, dict):
        return value.get(lang()) or value.get(DEFAULT_LANG) or next(iter(value.values()), "")
    return value


def num(x, digits=1):
    return f"{x:.{digits}f}".replace(".", tr("num.decimal"))


def gib(mib):
    """Memory size for messages: 27000 -> '26.4 GB' / '26,4 Go'."""
    return f"{num(mib / 1024)} {tr('unit.gb')}"
