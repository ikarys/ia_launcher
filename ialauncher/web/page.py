"""The HTML shell of every view, in the UI language: {{t:key}} replaced by the text (no flash of
untranslated text), plus the settings and texts the page's JS needs."""
import html
import json
import re

from .. import config, i18n
from ..services.settings import THEMES

VIEWS = ("/", "/index.html", "/models", "/modeles", "/settings")  # /modeles: old address of /models
_TEXT = re.compile(r"\{\{t:([\w.]+)\}\}")


def render(settings):
    lang, theme = settings.values["lang"], settings.values["theme"]
    boot = {"lang": lang, "theme": theme, "themes": THEMES,
            "langs": {code: texts.get("lang.name", code) for code, texts in i18n.LOCALES.items()},
            "strings": i18n.LOCALES[i18n.DEFAULT_LANG] | i18n.LOCALES.get(lang, {})}
    page = (config.WEB_DIR / "index.html").read_text()
    page = _TEXT.sub(lambda m: html.escape(i18n.tr(m[1])), page)
    page = (page.replace("{{LANG}}", lang).replace("{{THEME}}", theme)
            .replace("{{BOOT}}", json.dumps(boot, ensure_ascii=False).replace("</", "<\\/")))
    return page.encode()
