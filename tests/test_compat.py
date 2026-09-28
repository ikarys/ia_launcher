from ialauncher.domain import compat

from .conftest import make_engine

GB = 2**30
HW = {"cc": 12.0, "vram_usable_mib": 30000, "vram_free_mib": 30000, "ram_mib": 48000, "disk_free": 900 * GB}
DECISION = make_engine(label="decider", kinds=["decision"], file_ext=[], command=["/bin/decide"],
                       provides_repos=["org/decider"], uses=["hf/models--org--decider"])


def context(engines=None, installed=True, has=True, hw=HW, suggest=lambda fmt, kind, repo: None):
    return compat.Context(engines={"llama": make_engine()} if engines is None else engines, hw=hw,
                          installed=lambda eid: installed, lib_has=lambda rel: has, suggest=suggest)


def verdict(size, fmt="gguf", quant=None, ctx=None, repo="org/x", kind="llm"):
    return compat.fit(size, fmt, quant, ctx or context(), repo, kind)[0]


def test_fits_on_gpu():
    assert verdict(10 * GB) == "gpu"


def test_gguf_too_big_for_vram_runs_partly_on_cpu():
    assert verdict(40 * GB) == "partial"


def test_too_big_even_with_ram():
    assert verdict(90 * GB) == "no"
    assert verdict(40 * GB, fmt="ninfer", ctx=context({"n": make_engine(file_ext=[".ninfer"])})) == "no"


def test_no_engine_for_the_format():
    assert verdict(GB, fmt="safetensors") == "incompatible"


def test_engine_for_another_kind():
    assert verdict(GB, kind="tts") == "incompatible"


def test_engine_declared_but_not_installed():
    assert verdict(GB, ctx=context(installed=False)) == "incompatible"


def test_gpu_too_old_for_the_quantization():
    assert verdict(GB, quant="NVFP4", ctx=context(hw=HW | {"cc": 8.6})) == "incompatible"


def test_not_enough_disk():
    assert verdict(GB, ctx=context(hw=HW | {"disk_free": GB // 2})) == "disk"


def test_engine_fetching_its_own_weights():
    engines = {"llama": make_engine(), "decider": DECISION}
    assert verdict(GB, fmt="safetensors", repo="org/decider", ctx=context(engines)) == "installed"
    assert verdict(GB, fmt="safetensors", repo="org/decider", ctx=context(engines, has=False)) == "incompatible"


def test_variants_group_shards_and_suggest_missing_engines():
    files = [{"name": "m-Q4_K_M-00001-of-00002.gguf", "size": 3 * GB},
             {"name": "m-Q4_K_M-00002-of-00002.gguf", "size": 3 * GB},
             {"name": "mmproj-F16.gguf", "size": GB},
             {"name": "model.safetensors", "size": 4 * GB},
             {"name": "config.json", "size": 1000}]
    suggested = []
    ctx = context(suggest=lambda fmt, kind, repo: suggested.append(fmt) or {"id": "vllm"})
    out = {v["name"]: v for v in compat.variants("org/m", files, "llm", ctx)}
    assert out["m-Q4_K_M.gguf"]["size"] == 6 * GB and out["m-Q4_K_M.gguf"]["quant"] == "Q4_K_M"
    assert out["mmproj-F16.gguf"]["verdict"] == "extra"
    st = out["Safetensors weights (whole repository)"]
    assert st["verdict"] == "install" and st["suggest"] == {"id": "vllm"}
    assert "config.json" in st["files"] and suggested == ["safetensors"]


def test_tts_repository_suggests_the_tts_engine():
    tts = make_engine(label="omni", kinds=["tts"], file_ext=[".safetensors"])
    files = [{"name": "model.safetensors", "size": 4 * GB}, {"name": "config.json", "size": 1000}]
    asked = []
    ctx = compat.Context(engines={"llama": make_engine(), "omni": tts}, hw=HW,
                         installed=lambda eid: eid == "llama", lib_has=lambda rel: True,
                         suggest=lambda fmt, kind, repo: asked.append((fmt, kind)) or {"id": "omni"})
    [v] = compat.variants("Qwen/tts", files, "tts", ctx)
    assert v["verdict"] == "install" and v["suggest"] == {"id": "omni"}
    assert asked == [("safetensors", "tts")]
    assert v["files"] == ["model.safetensors", "config.json"]


def test_incompatible_without_a_suggestion_stays_incompatible():
    files = [{"name": "model.safetensors", "size": 4 * GB}, {"name": "config.json", "size": 1000}]
    [v] = compat.variants("org/m", files, "llm", context())
    assert v["verdict"] == "incompatible" and "suggest" not in v


def test_quant_of():
    assert compat.quant_of("Qwen3-27B-UD-Q4_K_XL.gguf") == "Q4_K_XL"
    assert compat.quant_of("model-NVFP4.ninfer") == "NVFP4"
    assert compat.quant_of("model.gguf") is None
