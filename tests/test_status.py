import pytest

from hominfer.domain.status import model_state, model_vram


@pytest.mark.parametrize("kw, expected", [
    ({"stopping": True, "running": True, "healthy": True, "failed": False}, "stopping"),
    ({"stopping": False, "running": False, "healthy": False, "failed": True}, "error"),
    ({"stopping": False, "running": False, "healthy": False, "failed": False}, "stopped"),
    ({"stopping": False, "running": True, "healthy": False, "failed": False}, "starting"),
    ({"stopping": False, "running": True, "healthy": True, "failed": False}, "ready"),
])
def test_model_state(kw, expected):
    assert model_state(**kw) == expected


def test_vram_of_the_only_model_on_the_gpu():
    assert model_vram("a", {"a": True, "b": False}, 25000, 1500, True, None) == (23500, "live")
    assert model_vram("a", {"a": True}, 25000, 1500, False, None) == (23500, "estimate")


def test_vram_on_cpu():
    assert model_vram("b", {"a": True, "b": False}, 25000, 1500, True, None) == (0, "cpu")


def test_vram_shared_gpu_uses_the_load_measure():
    on_gpu = {"a": True, "b": True}
    assert model_vram("a", on_gpu, 25000, 1500, True, 20000) == (20000, "load")
    assert model_vram("a", on_gpu, 25000, 1500, True, None) == (None, "shared")
