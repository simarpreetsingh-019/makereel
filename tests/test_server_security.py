"""The local server only answers requests addressed to this computer (DNS-rebinding protection)."""
import http.client
import threading
from http.server import ThreadingHTTPServer

import pytest

from makereel.api import routes, server
from makereel.services.jobs import JobManager
from makereel.services.watcher import Watcher


@pytest.fixture
def running(tmp_path):
    def start(password=None):
        jobs = JobManager(tmp_path / "makereel.json")
        api = routes.build(jobs, Watcher(jobs, tmp_path / "makereel.json"))
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), server._handler(api, password, ()))
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        started.append(httpd)
        return httpd.server_address[1]
    started = []
    yield start
    for h in started:
        h.shutdown()


def get(port, host, path="/api/v1/health", origin=None):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    headers = {"Host": host, **({"Origin": origin} if origin else {})}
    c.request("GET", path, headers=headers)
    return c.getresponse().status


def test_local_names_allowed(running):
    port = running()
    for host in (f"localhost:{port}", f"127.0.0.1:{port}", f"[::1]:{port}", f"app.localhost:{port}"):
        assert get(port, host) == 200, host


def test_rebinding_blocked(running):
    port = running()
    # an attacker's domain pointed at 127.0.0.1: same-origin as itself, but not this computer's name
    assert get(port, f"evil.example:{port}", origin=f"http://evil.example:{port}") == 403
    assert get(port, f"evil.example:{port}", "/api/v1/settings") == 403


def test_cross_origin_blocked(running):
    port = running()
    assert get(port, f"localhost:{port}", origin="https://evil.example") == 403


def test_password_mode_allows_other_names_but_needs_the_password(running):
    port = running(password="s3cret")
    assert get(port, f"mybox.lan:{port}") == 401
