"""User settings (settings.json, local), for every browser: UI language, theme, models folder."""
import json
from pathlib import Path

from .. import config, i18n
from ..errors import LaunchError
from ..i18n import tr
from ..infra.files import read_json, write_atomic

THEMES = ["auto", "light", "dark", "cyber", "pixel", "neo"]
DEFAULTS = {"lang": i18n.DEFAULT_LANG, "theme": "auto", "models_dir": config.DEFAULT_MODELS_DIR}


def _folder(text):
    """'~/hominfer_models' -> Path, or None when it isn't an absolute path."""
    p = Path(str(text).strip()).expanduser()
    return p if str(text).strip() and p.is_absolute() else None


class Settings:
    def __init__(self, path, *, models_busy=lambda: False):
        """models_busy: () -> True while something writes into the models folder (downloads)."""
        self.path, self.models_busy = path, models_busy
        s = DEFAULTS | read_json(path, {})
        self.values = {"lang": s["lang"] if s["lang"] in i18n.LOCALES else DEFAULTS["lang"],
                       "theme": s["theme"] if s["theme"] in THEMES else DEFAULTS["theme"],
                       "models_dir": s["models_dir"] if _folder(s["models_dir"]) else DEFAULTS["models_dir"]}
        i18n.set_lang(self.values["lang"])

    def models_dir(self):
        """The models folder (created if missing)."""
        p = _folder(self.values["models_dir"])
        p.mkdir(parents=True, exist_ok=True)
        return p

    def update(self, body):
        new = self.values | {k: str(body[k]).strip() for k in DEFAULTS if k in body}
        if new["lang"] not in i18n.LOCALES:
            raise LaunchError(tr("settings.bad_lang"))
        if new["theme"] not in THEMES:
            raise LaunchError(tr("settings.bad_theme"))
        if new["models_dir"] != self.values["models_dir"]:
            self._check_models_dir(new["models_dir"])
        write_atomic(self.path, json.dumps(new, indent=2) + "\n")
        self.values = new
        i18n.set_lang(new["lang"])

    def _check_models_dir(self, text):
        folder = _folder(text)
        if not folder:
            raise LaunchError(tr("settings.bad_models_dir"))
        if self.models_busy():
            raise LaunchError(tr("settings.models_busy"))
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            raise LaunchError(tr("settings.models_dir_error", err=e.strerror or e))
