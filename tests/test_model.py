import pytest

from hominfer.domain import model as model_rules
from hominfer.errors import LaunchError

from .conftest import make_engine

ENGINES = {"test": make_engine(params={"ctx": {"label": "Context"},
                                       "fa": {"label": "Flash", "values": [["on", "enabled"], ["off", "disabled"]]}})}
GOOD = {"kind": "llm", "name": "My model", "engine": "test", "port": 8000, "file": "/m/model.gguf",
        "params": {"ctx": ["8192", "4096"], "fa": "on"}, "profiles": {"Small": {"ctx": "4096"}}}


def validate(c):
    model_rules.validate("my_model", c, ENGINES, listen_port=8090, file_exists=lambda p: True)


def test_valid_model():
    validate(GOOD)


@pytest.mark.parametrize("change, message", [
    ({"engine": "nope"}, "unknown engine"),
    ({"port": 8090}, "invalid port"),
    ({"port": 80}, "invalid port"),
    ({"name": " "}, "name missing"),
    ({"file": "/m/model.bin"}, "runs .gguf files"),
    ({"params": {"nope": "1"}}, "unknown param"),
    ({"params": {"fa": "maybe"}}, "not in on, off"),
    ({"params": {"ctx": "8192; rm -rf"}}, "invalid value"),
    ({"extra_args": ["--a b"]}, "extra_args"),
    ({"profiles": {"Big": {"ctx": "65536"}}}, "not in the menu"),
])
def test_invalid_model(change, message):
    with pytest.raises(LaunchError, match=message):
        validate(GOOD | change)


def test_missing_file():
    with pytest.raises(LaunchError, match="file not found"):
        model_rules.validate("m", GOOD, ENGINES, listen_port=8090, file_exists=lambda p: False)


def test_resolve_menus_and_fixed_values():
    m = model_rules.resolve("my_model", GOOD, ENGINES["test"], vram_mib=5000)
    assert m["fixed"] == {"fa": "on"}
    assert m["options"] == [{"key": "ctx", "label": "Context", "choices": [["8192", "8192"], ["4096", "4096"]],
                             "default": "8192"}]
    assert m["vram_mib"] == 5000 and m["match"] is None


def test_engine_labels_fill_unlabelled_choices():
    assert model_rules.labelled({"values": [["on", "enabled"]]}, ["on", ["off", "no"]]) == [["on", "enabled"],
                                                                                        ["off", "no"]]


def test_clean_options_keeps_only_menu_values():
    m = model_rules.resolve("my_model", GOOD, ENGINES["test"], vram_mib=0)
    assert model_rules.clean_options(m, {"ctx": "4096", "evil": "x"}) == {"ctx": "4096"}
    assert model_rules.clean_options(m, {"ctx": "999999"}) == {"ctx": "8192"}


def test_vram_estimate():
    assert model_rules.vram_estimate(10 * 2**30) == round(10 * 1024 * 1.1 + 1024)
