"""URL -> service call. A handler gets (app, match, body) and returns the JSON payload."""
import re
from dataclasses import dataclass
from typing import Callable

from . import presenters

OK = {"ok": True}
PAGES = ("/", "/index.html", "/modeles")  # one page; /modeles = the model management view


class NotFound(Exception):
    pass


@dataclass
class Route:
    method: str
    pattern: re.Pattern
    handler: Callable


def _model(app, mid):
    if mid not in app.registry.models:
        raise NotFound
    return mid


def _then_poll(app, result=OK):
    app.supervisor.poll()  # the page sees the new state at once
    return result


def _update(app, mid):
    if not app.registry.models.get(mid, {}).get("repo"):
        raise NotFound
    app.updates.start(mid)
    return _then_poll(app)


def _check(app, mid):
    if not app.registry.models.get(mid, {}).get("repo"):
        raise NotFound
    return app.updates.check(mid)


def _save_model(app, match, body):
    mid = match[1]
    if match[2]:
        app.editor.delete(mid)
    else:
        app.editor.save(mid, body)
    return OK


def _set_profile(app, match, body):
    if match[1] not in app.registry.cfg:
        raise NotFound
    app.editor.set_profile(match[1], body.get("name"), body.get("opts"))
    return OK


def _start_stop(app, match, body):
    mid = _model(app, match[2])
    if match[1] == "start":
        app.supervisor.start(mid, body)
    else:
        app.supervisor.stop(mid)
    return _then_poll(app)


def _download(app, body):
    app.downloads.start(str(body.get("repo", "")), [str(f) for f in body.get("files", [])])
    return OK


def _install(app, cid):
    gpu = app.supervisor.gpu()
    app.catalog.install(cid, gpu and gpu["cc"])
    return OK


def _do(action):
    """A handler running action(app) and answering {"ok": true}."""
    def handler(app, match, body):
        action(app, match, body)
        return OK
    return handler


ROUTES = [
    Route("GET", re.compile(r"/api/status"), lambda app, m, b: app.supervisor.snapshot),
    Route("GET", re.compile(r"/api/models"), lambda app, m, b: presenters.models(app)),
    Route("GET", re.compile(r"/api/library"), lambda app, m, b: presenters.library(app)),
    Route("GET", re.compile(r"/api/engines"), lambda app, m, b: presenters.engines(app)),
    Route("GET", re.compile(r"/api/logs/(\w+)"), lambda app, m, b: {"log": app.supervisor.log(_model(app, m[1]))}),
    Route("POST", re.compile(r"/api/check/(\w+)"), lambda app, m, b: _check(app, m[1])),
    Route("POST", re.compile(r"/api/update/(\w+)"), lambda app, m, b: _update(app, m[1])),
    Route("POST", re.compile(r"/api/model/(\w+)(/delete)?"), _save_model),
    Route("POST", re.compile(r"/api/profile/(\w+)"), _set_profile),
    Route("POST", re.compile(r"/api/hf/info"), lambda app, m, b: app.hub.check(str(b.get("repo", "")).strip())),
    Route("POST", re.compile(r"/api/hf/download"), lambda app, m, b: _download(app, b)),
    Route("POST", re.compile(r"/api/hf/cancel/(\d+)"), _do(lambda app, m, b: app.downloads.cancel(int(m[1])))),
    Route("POST", re.compile(r"/api/engines/install/([\w.-]+)"), lambda app, m, b: _install(app, m[1])),
    Route("POST", re.compile(r"/api/library/delete"), _do(lambda app, m, b: app.library.delete(str(b.get("path", ""))))),
    Route("POST", re.compile(r"/api/reload"), _do(lambda app, m, b: app.registry.reload_models())),
    Route("POST", re.compile(r"/api/(start|stop)/(\w+)"), _start_stop),
]


def match(method, path):
    for route in ROUTES:
        if route.method == method and (m := route.pattern.fullmatch(path)):
            return route.handler, m
    return None, None
