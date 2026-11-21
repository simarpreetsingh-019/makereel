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


def test_shots_hold_then_move():
    centres = [0.5] * 12 + [0.8] * 12          # speaker moves right after 4 s
    shots = framing.shots_from_centres(centres, 3)
    assert [s["x"] for s in shots] == [0.5, 0.8] and shots[0]["start"] == 0.0


def test_shots_ignore_small_wobble_and_need_faces():
    assert len(framing.shots_from_centres([0.5, 0.52, 0.49, 0.51] * 6, 3)) == 1
    assert framing.shots_from_centres([None] * 10 + [0.5], 3) is None


def test_clean_and_shift_shots():
    shots = framing.clean_shots([{"start": 5, "x": 0.8}, {"start": 1, "x": 1.4}, {"start": "x"}], 10)
    assert shots == [{"start": 0.0, "x": 1.0}, {"start": 5.0, "x": 0.8}]
    assert framing.shift_shots(shots, 3, 7) == [{"start": 0.0, "x": 1.0}, {"start": 2.0, "x": 0.8}]
    assert framing.shift_shots(shots, 6, 4) == [{"start": 0.0, "x": 0.8}]


def test_moment_length_follows_the_moment():
    import numpy as np

    from makereel.core import highlights
    curve = np.full(600, -1.0)
    curve[100:105] = 3.0                      # a quick reaction
    curve[300:480] = 1.0                      # a 3-minute funny bit, with a short lull inside
    curve[380:385] = -1.0
    curve[350] = 4.0
    s, e = highlights.moment(curve, 102, max_len=240)
    assert e - s < 45, (s, e)                 # stays short
    s, e = highlights.moment(curve, 350, max_len=240)
    assert e - s >= 170 and e <= 485, (s, e)  # grows to cover the whole bit, lull included
    s, e = highlights.moment(curve, 350, max_len=60)
    assert e - s <= 60                        # never past the longest-reel setting
    picks = highlights.candidates(curve, k=2, max_len=240)
    assert len(picks) == 2 and max(c.end - c.start for c in picks) >= 170


def test_ai_word_fix_keeps_fixes_and_rejects_rewrites(monkeypatch):
    from makereel.core import judge
    ai = {"provider": "local", "model": "", "base_url": "", "weight": 0.5}
    monkeypatch.setattr(judge, "enabled", lambda a: True)
    monkeypatch.setattr(judge, "_ask", lambda a, p: "bhai mission time limited hai")
    assert judge.fix_words("bhai misan taim limited hai", "hi", ai) == "bhai mission time limited hai"
    rewrite = "Brother, this mission has a strict time limit and we must hurry now."
    monkeypatch.setattr(judge, "_ask", lambda a, p: rewrite)
    assert judge.fix_words("bhai misan taim limited hai", "hi", ai) is None      # rewrote it: not trusted


def test_most_replayed_graph_lifts_the_curve(monkeypatch):
    import numpy as np

    from makereel.core import pipeline, sources
    monkeypatch.setattr(sources, "youtube_heatmap", lambda url: [{"start_time": 50, "end_time": 60, "value": 1.0},
                                                                 {"start_time": 0, "end_time": 50, "value": 0.1}])
    parts = {}
    curve = pipeline._add_replays(np.zeros(100), parts, {"url": "https://youtube.com/watch?v=x"}, 100)
    assert curve[55] > curve[10] and "replays" in parts
    assert pipeline._add_replays(np.zeros(10), {}, {"url": "x", "live_status": "is_live"}, 10).sum() == 0


def test_action_signal_only_for_gameplay(monkeypatch):
    from pathlib import Path

    import numpy as np

    from makereel.core import pipeline, signals
    monkeypatch.setattr(signals, "motion", lambda v, n: np.r_[np.zeros(50), np.ones(10), np.zeros(40)])
    parts = {}
    lifted = pipeline._add_action(np.zeros(100), parts, Path("v.mp4"), 100, {"profile": "gameplay"})
    assert lifted[55] > lifted[10] and "action" in parts
    assert pipeline._add_action(np.zeros(100), {}, Path("v.mp4"), 100, {"profile": "talk"}).sum() == 0
