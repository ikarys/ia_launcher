"""User settings (settings.json, local): UI language and default theme, for every browser."""
import json

from .. import i18n
from ..errors import LaunchError
from ..i18n import tr
from ..infra.files import read_json, write_atomic

THEMES = ["auto", "light", "dark", "cyber", "pixel", "neo"]
DEFAULTS = {"lang": i18n.DEFAULT_LANG, "theme": "auto"}


class Settings:
    def __init__(self, path):
        self.path = path
        s = DEFAULTS | read_json(path, {})
        self.values = {"lang": s["lang"] if s["lang"] in i18n.LOCALES else DEFAULTS["lang"],
                       "theme": s["theme"] if s["theme"] in THEMES else DEFAULTS["theme"]}
        i18n.set_lang(self.values["lang"])

    def update(self, body):
        new = self.values | {k: str(body[k]) for k in DEFAULTS if k in body}
        if new["lang"] not in i18n.LOCALES:
            raise LaunchError(tr("settings.bad_lang"))
        if new["theme"] not in THEMES:
            raise LaunchError(tr("settings.bad_theme"))
        write_atomic(self.path, json.dumps(new, indent=2) + "\n")
        self.values = new
        i18n.set_lang(new["lang"])
