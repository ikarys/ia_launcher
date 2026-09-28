"""Service data -> JSON for the page (config texts in the UI language)."""
from ..domain.kinds import TASK_KIND, kind_labels
from ..i18n import loc


def _choices(values):
    return [[x, loc(label)] for x, label in values]


def models(app):
    reg = app.registry
    out = {}
    for mid, m in reg.models.items():
        out[mid] = m | {"engine": loc(m["engine"]),
                        "options": [o | {"label": loc(o["label"]), "choices": _choices(o["choices"])}
                                    for o in m["options"]]}
    engines = {eid: {"label": loc(e["label"]), "needs_file": e["needs_file"], "file_ext": e["file_ext"],
                     "kinds": e.get("kinds"), "installed": reg.installed(eid),
                     "params": {k: p | {"label": loc(p["label"])} | ({"values": _choices(p["values"])}
                                                                    if "values" in p else {})
                                for k, p in e["params"].items()}}
               for eid, e in reg.engines.items()}
    return {"models": out, "kinds": kind_labels(), "task_kind": TASK_KIND, "engines": engines}


def library(app):
    lib = app.library
    return {"dir": str(lib.dir), "free": lib.free(), "items": lib.items(), "downloads": app.downloads.status(),
            "hardware": app.hub.hardware()}


def engines(app):
    gpu = app.supervisor.gpu()
    return {"catalog": app.catalog.status(gpu and gpu["cc"]),
            "configured": {eid: {"label": loc(e["label"]), "installed": app.registry.installed(eid)}
                           for eid, e in app.registry.engines.items()}}
