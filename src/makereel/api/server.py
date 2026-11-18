"""HTTP server: static web app, /media streaming, /api/v1 JSON, auth and CORS.

Standard library only, so it runs anywhere Python does (Windows, macOS, Linux, servers).

Security model
- Bound to 127.0.0.1 by default: only this computer can reach it.
- Without a password, only requests addressed to localhost / 127.0.0.1 / [::1] are answered. This blocks
  DNS rebinding: a web page pointing its own domain at 127.0.0.1 to drive the app from the browser.
- Any other host requires a password (HTTP Basic; the browser asks for it).
- Cross-origin requests are refused unless the origin is in MAKEREEL_ALLOWED_ORIGINS. That
  allow-list is how a hosted copy of the web app can drive this local engine
  (see docs/CLIENT_SIDE_PLAN.md); Chrome's Private Network Access preflight is answered too.
"""
from __future__ import annotations

import base64
import hmac
import json
import logging
import mimetypes
import re
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from ..config import env
from ..errors import Forbidden, MakereelError, NotFound
from ..services import library
from ..services.jobs import JobManager
from ..services.watcher import Watcher
from . import routes
from .router import Request, Response, parse_query

log = logging.getLogger(__name__)

WEB_ROOT = Path(__file__).resolve().parent.parent / "web"
LOCAL_HOSTS = ("127.0.0.1", "localhost", "::1")
MAX_JSON_BODY = 2 * 1024**2

mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("text/css", ".css")


def _handler(api, password: str | None, origins: tuple[str, ...]):
    class Handler(BaseHTTPRequestHandler):
        server_version = "makereel"
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt, *args):  # quiet: the app logs what matters
            log.debug("%s %s", self.address_string(), fmt % args)

        # ---------------------------------------------------------- plumbing
        def _cors(self) -> None:
            origin = self.headers.get("Origin", "").rstrip("/")
            if origin and origin in origins:
                self.send_header("Access-Control-Allow-Origin", origin)
                self.send_header("Vary", "Origin")
                self.send_header("Access-Control-Allow-Credentials", "true")

        def _host_allowed(self) -> bool:
            """Without a password, the Host header must name this computer (stops DNS rebinding)."""
            if password:
                return True
            host = self.headers.get("Host", "").strip().lower()
            name = host[1:host.index("]")] if host.startswith("[") and "]" in host else host.rsplit(":", 1)[0]
            return name in LOCAL_HOSTS or name.endswith(".localhost")

        def _cross_origin_refused(self) -> bool:
            origin = self.headers.get("Origin", "").rstrip("/")
            host = self.headers.get("Host", "")
            same = origin.endswith("//" + host)
            return bool(origin) and not same and origin not in origins

        def _authorized(self) -> bool:
            if not password:
                return True
            header = self.headers.get("Authorization", "")
            if header.startswith("Basic "):
                try:
                    _, given = base64.b64decode(header[6:]).decode().split(":", 1)
                    return hmac.compare_digest(given.encode(), password.encode())
                except (ValueError, UnicodeDecodeError):
                    return False
            return False

        def _send_json(self, body, status: int = 200, headers: dict | None = None) -> None:
            data = b"" if body is None else json.dumps(body, ensure_ascii=False).encode()
            self.send_response(status)
            self._cors()
            if data:
                self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            for k, v in (headers or {}).items():
                self.send_header(k, v)
            self.end_headers()
            if data and self.command != "HEAD":
                self.wfile.write(data)

        def _send_error(self, e: MakereelError) -> None:
            self._send_json({"error": e.to_dict()}, e.status)

        def _send_file(self, path: Path, download: bool = False) -> None:
            size = path.stat().st_size
            ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            start, end = 0, size - 1
            rng = re.match(r"bytes=(\d*)-(\d*)$", self.headers.get("Range", ""))
            if rng and size:  # browsers (Safari especially) need ranges to play and seek video
                a, b = rng.groups()
                start = int(a) if a else max(0, size - int(b or 0))
                end = min(int(b), size - 1) if a and b else size - 1
                if start > end:
                    self.send_response(416)
                    self.send_header("Content-Range", f"bytes */{size}")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                self.send_response(206)
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            else:
                self.send_response(200)
            self._cors()
            self.send_header("Content-Type", ctype)
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Length", str(end - start + 1))
            self.send_header("Cache-Control", "no-cache")
            if download:
                self.send_header("Content-Disposition", f'attachment; filename="{path.name}"')
            self.end_headers()
            if self.command == "HEAD":
                return
            with path.open("rb") as f:
                f.seek(start)
                left = end - start + 1
                while left > 0:
                    chunk = f.read(min(1 << 20, left))
                    if not chunk:
                        break
                    try:
                        self.wfile.write(chunk)
                    except (BrokenPipeError, ConnectionResetError):
                        return  # viewer scrolled away mid-stream: normal
                    left -= len(chunk)

        def _static(self, path: str) -> None:
            rel = "index.html" if path in ("", "/") else path.lstrip("/")
            target = (WEB_ROOT / unquote(rel)).resolve()
            if WEB_ROOT not in target.parents and target != WEB_ROOT / "index.html":
                raise Forbidden("outside the web app")
            if not target.is_file():
                target = WEB_ROOT / "index.html"  # single-page app fallback
            self._send_file(target)

        # ---------------------------------------------------------- dispatch
        def _dispatch(self) -> None:
            url = urlparse(self.path)
            try:
                if not self._host_allowed():
                    raise Forbidden("this address is not allowed",
                                    "Open makereel at http://localhost, or set a password to reach it by another name.")
                if self.command == "OPTIONS":
                    return self._preflight()
                if self._cross_origin_refused():
                    raise Forbidden("this origin is not allowed",
                                    "Add it to MAKEREEL_ALLOWED_ORIGINS on the machine running makereel.")
                if not self._authorized():
                    self.send_response(401)
                    self.send_header("WWW-Authenticate", 'Basic realm="makereel"')
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                if url.path.startswith("/api/"):
                    return self._api(url)
                if url.path.startswith("/media/"):
                    query = parse_query(url.query)
                    return self._send_file(library.media_file(unquote(url.path[len("/media/"):])),
                                           "download" in query)
                if url.path.startswith("/brand/"):
                    from ..core import branding
                    name = Path(unquote(url.path[len("/brand/"):])).name
                    path = branding.brand_dir() / name
                    if name not in branding.LOGO_NAMES or not path.is_file():
                        raise NotFound("no logo")
                    return self._send_file(path)
                if self.command in ("GET", "HEAD"):
                    return self._static(url.path)
                raise NotFound("not found")
            except MakereelError as e:
                self._send_error(e)
            except (BrokenPipeError, ConnectionResetError):
                pass
            except Exception as e:  # noqa: BLE001 - never crash the server on one request
                log.exception("unhandled error on %s %s", self.command, self.path)
                self._send_error(MakereelError(f"internal error: {e}"))

        def _api(self, url) -> None:
            handler, params = api.match(self.command, url.path)
            length = int(self.headers.get("Content-Length") or 0)
            streaming = url.path.endswith("/jobs/upload") or url.path.startswith("/api/v1/brand/")
            if not streaming and length > MAX_JSON_BODY:
                raise MakereelError("request body too large")
            req = Request(self.command, url.path, parse_query(url.query), self.headers,
                          b"" if streaming else self.rfile.read(length), params,
                          stream=self.rfile if streaming else None, length=length)
            result = handler(req)
            if isinstance(result, Response):
                self._send_json(result.body, result.status, result.headers)
            else:
                self._send_json(result)

        def _preflight(self) -> None:
            origin = self.headers.get("Origin", "").rstrip("/")
            self.send_response(204 if origin in origins else 403)
            self._cors()
            if origin in origins:
                self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, PATCH, DELETE, OPTIONS")
                self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
                self.send_header("Access-Control-Allow-Private-Network", "true")
                self.send_header("Access-Control-Max-Age", "600")
            self.send_header("Content-Length", "0")
            self.end_headers()

        do_GET = do_HEAD = do_POST = do_PUT = do_PATCH = do_DELETE = do_OPTIONS = _dispatch

    return Handler


def serve(host: str | None = None, port: int | None = None, password: str | None = None,
          open_browser: bool = True, watch: bool = False) -> None:
    cfg = env()
    host, port = host or cfg.host, port or cfg.port
    password = password or cfg.password
    if host not in LOCAL_HOSTS and not password:
        raise MakereelError("refusing to listen on the network without a password",
                            "Pass --password or set MAKEREEL_WEB_PASSWORD.")

    jobs = JobManager()
    watcher = Watcher(jobs)
    api = routes.build(jobs, watcher)
    httpd = ThreadingHTTPServer((host, port), _handler(api, password, cfg.allowed_origins))
    httpd.daemon_threads = True

    shown = "localhost" if host in ("0.0.0.0", "::", "127.0.0.1") else host
    url = f"http://{shown}:{port}"
    log.info("makereel web: %s   (Ctrl+C to quit)", url)
    if watch:
        watcher.start()
    if open_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        watcher.stop()
        jobs.stop_all_live()
        httpd.server_close()
