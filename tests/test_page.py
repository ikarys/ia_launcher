"""The page is rendered in the UI language, and every text it asks for exists in every language."""
import json
import re

import pytest

from ialauncher import config, i18n
from ialauncher.web import page

JS_KEY = re.compile(r"""\bt\(\s*["']([\w.]+)["']""")
# keys built at run time: prefix + a value the page knows
DYNAMIC = {"ui.theme.": ["auto", "light", "dark", "cyber", "pixel", "neo", "default"],
           "ui.state.": ["stopped", "starting", "ready", "stopping", "error"],
           "ui.vram.": ["live", "estimate", "load", "shared", "cpu"],
           "ui.verdict.": ["installed", "gpu", "partial", "no", "incompatible", "disk", "extra"],
           "ui.src.": ["hf_cache", "hf", "local"],
           "ui.col.": ["model", "kind", "engine", "file", "port", "runs", "state", "quant", "version", "date", "size",
                       "used_by"],
           "ui.eng.state.": ["configured", "present", "available"]}


class FakeSettings:
    def __init__(self, lang, theme="cyber"):
        self.values = {"lang": lang, "theme": theme}


def page_literals():
    html = (config.WEB_DIR / "index.html").read_text()
    js = "\n".join(p.read_text() for p in config.WEB_DIR.glob("js/**/*.js"))
    return set(re.findall(r"\{\{t:([\w.]+)\}\}", html)) | set(JS_KEY.findall(js))


def test_dynamic_keys_are_declared_here():
    assert {k for k in page_literals() if k.endswith(".")} <= set(DYNAMIC)


@pytest.mark.parametrize("lang", list(i18n.LOCALES))
def test_every_key_of_the_page_exists(lang):
    keys = {k for k in page_literals() if not k.endswith(".")} | {
        prefix + v for prefix, values in DYNAMIC.items() for v in values}
    assert keys - set(i18n.LOCALES[lang]) == set()


@pytest.mark.parametrize("lang", list(i18n.LOCALES))
def test_render(lang):
    i18n.set_lang(lang)
    html = page.render(FakeSettings(lang)).decode()
    assert "{{" not in html
    assert f'<html lang="{lang}" data-default-theme="cyber">' in html
    assert i18n.tr("ui.nav.settings") in html
    boot = json.loads(re.search(r'<script id="boot" type="application/json">(.*?)</script>', html, re.S)[1])
    assert boot["lang"] == lang and "cyber" in boot["themes"] and boot["strings"]["ui.nav.settings"]
