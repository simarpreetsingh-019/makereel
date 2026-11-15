import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from makereel.core import framing, judge


class _FakeLLM(BaseHTTPRequestHandler):
    reply = ""

    def do_POST(self):  # noqa: N802
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        _FakeLLM.seen = body
        data = json.dumps({"choices": [{"message": {"content": _FakeLLM.reply}}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *a):
        pass


def _serve():
    srv = HTTPServer(("127.0.0.1", 0), _FakeLLM)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


CANDS = [{"id": 0, "length": 30, "why": ["loud"], "text": "oh no he jumped off the roof"},
         {"id": 1, "length": 30, "why": [], "text": "anyway let me check the map"}]


def test_local_judge_end_to_end():
    srv = _serve()
    _FakeLLM.reply = json.dumps({"clips": [
        {"id": 0, "hook": 9, "engagement": 9, "value": 7, "shareability": 8, "title": "HE JUMPED",
         "reason": "big moment"},
        {"id": 1, "hook": 2, "engagement": 1, "value": 2, "shareability": 1, "title": "map", "reason": "filler"}]})
    ai = {"provider": "local", "base_url": f"http://127.0.0.1:{srv.server_port}/v1", "model": "test", "weight": 0.5}
    scores = judge.judge(CANDS, ai, "gameplay")
    srv.shutdown()
    assert scores[0]["title"] == "HE JUMPED" and scores[1]["hook"] == 2
    assert _FakeLLM.seen["model"] == "test" and "oh no he jumped" in _FakeLLM.seen["messages"][1]["content"]


def test_judge_failure_is_harmless():
    srv = _serve()
    _FakeLLM.reply = "sorry, I can't do JSON today"
    ai = {"provider": "local", "base_url": f"http://127.0.0.1:{srv.server_port}/v1", "model": "x"}
    assert judge.judge(CANDS, ai, "talk") == {}
    srv.shutdown()
    assert judge.judge(CANDS, {"provider": "local", "base_url": "http://127.0.0.1:9/v1", "model": "x"}, "talk") == {}
    assert judge.judge(CANDS, {"provider": "off"}, "talk") == {}


def test_blend_reorders_by_ai():
    blended = judge.blend([5.0, 4.0], [0.1, 0.9], weight=0.7)
    assert blended[1] > blended[0]


def test_camera_holds_then_glides():
    centres = [0.5] * 12 + [0.8] * 12          # speaker moves right after 4 s
    keys = framing.camera_path(centres)
    xs = [c for _, c in keys]
    assert xs[0] == 0.5 and xs[-1] == 0.8 and len(keys) <= 5   # one deliberate move, not jitter


def test_camera_ignores_small_wobble_and_needs_faces():
    assert len(framing.camera_path([0.5, 0.52, 0.49, 0.51] * 6)) == 2
    assert framing.camera_path([None] * 10 + [0.5]) is None
