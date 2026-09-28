import json

from ialauncher.services.registry import Registry

ENGINE = {"label": "Test engine", "kinds": ["llm"], "file_ext": [".gguf"],
          "command": ["/bin/serve", "-m", "{file}", "--port", "{port}"],
          "health": "/health", "endpoint": "/v1", "procs": ["serve"]}


def registry(tmp_path):
    return Registry(tmp_path / "engines.json", tmp_path / "models.json", listen_port=8090)


def test_first_run_without_config(tmp_path):
    r = registry(tmp_path)
    assert r.engines == {} and r.models == {}


def test_add_engine_creates_the_file(tmp_path):
    r = registry(tmp_path)
    assert r.add_engine("test", ENGINE) is True
    assert "test" in r.engines
    assert json.loads((tmp_path / "engines.json").read_text())["test"]["label"] == "Test engine"
    assert r.add_engine("test", ENGINE | {"label": "Other"}) is False  # an existing id is left untouched
