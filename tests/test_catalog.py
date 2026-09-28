"""The engine catalog shipped with the launcher: every entry is complete and its engine block is
valid and buildable."""
import json

import pytest

from ialauncher import config
from ialauncher.domain import engine as engine_rules

CATALOG = json.loads((config.CATALOG_DIR / "catalog.json").read_text())


@pytest.mark.parametrize("cid", list(CATALOG))
def test_catalog_entry(cid):
    c = CATALOG[cid]
    assert {"label", "desc", "url", "dir", "script", "disk_gb", "minutes", "engine"} <= set(c)
    assert (config.CATALOG_DIR / c["script"]).is_file()
    engine_rules.validate(cid, json.loads(json.dumps(c["engine"])))
    e = engine_rules.normalize(c["engine"])
    ext = (e["file_ext"] or [""])[0]
    model = {"engine": cid, "port": 9000, "file": f"/models/org--repo/model{ext}" if ext else None}
    argv, _, _ = engine_rules.build_command(e, "m", model, {}, vram_need=0, free_vram=0, models_dir="/models")
    assert argv and all(argv)
