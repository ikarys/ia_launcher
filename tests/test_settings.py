import json
from pathlib import Path

import pytest

from hominfer import i18n
from hominfer.errors import LaunchError
from hominfer.services.settings import DEFAULTS, Settings


@pytest.fixture
def path(tmp_path):
    return tmp_path / "settings.json"


def test_defaults_without_a_file(path):
    s = Settings(path)
    assert s.values == DEFAULTS
    assert s.models_dir() == Path(DEFAULTS["models_dir"]).expanduser()


def test_update_writes_the_file_and_the_language(path, tmp_path):
    s = Settings(path)
    s.update({"lang": "fr", "theme": "cyber", "models_dir": str(tmp_path / "models")})
    assert json.loads(path.read_text()) == s.values and i18n.lang() == "fr"
    assert s.models_dir().is_dir()  # created
    assert Settings(path).values == s.values  # read back


def test_models_dir_accepts_home_paths(path):
    s = Settings(path)
    s.update({"models_dir": "~/hominfer_models"})
    assert s.models_dir() == Path.home() / "hominfer_models"


@pytest.mark.parametrize("change, message", [
    ({"lang": "xx"}, "Unknown language"),
    ({"theme": "pink"}, "Unknown theme"),
    ({"models_dir": "relative/models"}, "absolute path"),
    ({"models_dir": "  "}, "absolute path"),
])
def test_update_rejects(path, change, message):
    s = Settings(path)
    with pytest.raises(LaunchError, match=message):
        s.update(change)
    assert not path.exists()


def test_models_dir_cant_move_during_a_download(path, tmp_path):
    s = Settings(path, models_busy=lambda: True)
    with pytest.raises(LaunchError, match="download is running"):
        s.update({"models_dir": str(tmp_path / "elsewhere")})
    s.update({"theme": "neo"})  # other settings still change


def test_invalid_file_values_fall_back_to_defaults(path):
    path.write_text(json.dumps({"lang": "xx", "theme": "pink", "models_dir": "relative"}))
    assert Settings(path).values == DEFAULTS
