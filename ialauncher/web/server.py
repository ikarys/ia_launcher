"""HTTP transport: JSON in / out, errors -> status codes, the page, same-origin POSTs only."""
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .. import config
from ..errors import LaunchError
from ..i18n import tr
from . import routes

MAX_BODY = 1 << 20


def make_handler(app):
    class Handler(BaseHTTPRequestHandler):
        server_version = "ia-launcher"

        def log_message(self, fmt, *args):
            pass

        def _send(self, code, body, ctype="application/json; charset=utf-8"):
            data = body if isinstance(body, bytes) else json.dumps(body).encode()
            self.send_response(code)
            self.send_header("content-type", ctype)
            self.send_header("content-length", str(len(data)))
            self.send_header("cache-control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def _body(self):
            n = int(self.headers.get("content-length") or 0)
            if n > MAX_BODY:
                raise LaunchError(tr("http.too_big"))
            return json.loads(self.rfile.read(n) or b"{}")

        def _dispatch(self, method):
            handler, match = routes.match(method, self.path)
            if not handler:
                return self._send(404, {"error": tr("http.not_found")})
            try:
                body = self._body() if method == "POST" else {}
                self._send(200, handler(app, match, body))
            except routes.NotFound:
                self._send(404, {"error": tr("http.not_found")})
            except LaunchError as e:
                self._send(409, {"error": str(e)})
            except Exception as e:
                self._send(500, {"error": f"{type(e).__name__}: {e}"})

        def do_GET(self):
            if self.path in routes.PAGES:
                return self._send(200, config.INDEX_HTML.read_bytes(), "text/html; charset=utf-8")
            self._dispatch("GET")

        def do_POST(self):
            # the page is served on the LAN: refuse POSTs from another site (origin != requested host)
            origin = self.headers.get("origin")
            if origin and origin != f"http://{self.headers.get('host')}":
                return self._send(403, {"error": tr("http.bad_origin")})
            self._dispatch("POST")

    return Handler


def serve(app, host, port):
    server = ThreadingHTTPServer((host, port), make_handler(app))
    server.daemon_threads = True
    return server
