import pytest

from hominfer import i18n
from hominfer.domain import engine as engine_rules


@pytest.fixture(autouse=True)
def english():
    i18n.set_lang("en")


def make_engine(**over):
    """A valid normalized engine; override any field."""
    raw = {"label": "Test engine", "kinds": ["llm"], "file_ext": [".gguf"],
           "command": ["/bin/serve", "-m", "{file}", "--port", "{port}", "-c", "{ctx}"],
           "health": "/health", "endpoint": "/v1", "procs": ["serve"],
           "params": {"ctx": {"label": "Context", "default": "4096"}}} | over
    engine_rules.validate("test", raw)
    return engine_rules.normalize(raw)
