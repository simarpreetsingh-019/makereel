import numpy as np

from makereel.core import highlights, pipeline, sources


def test_credits_link_to_the_moment():
    meta = {"url": "https://www.youtube.com/watch?v=abc", "channel": "Some Streamer",
            "channel_url": "https://youtube.com/@s", "title": "Big stream", "tags": ["GTA 6"], "offset": 100}
    c = pipeline.credits(meta, 20.4, "gameplay", "WOW")
    assert c["source"].endswith("t=120s")
    assert "#somestreamer" in c["caption"] and "#gta6" in c["caption"]
    assert "All rights belong to the original creator." in c["caption"]


def test_hook_prefers_exclamations():
    assert pipeline.make_hook("we walked around. oh no he's dead!") == "oh no he's dead!"


def test_candidates_do_not_overlap():
    curve = np.zeros(300)
    curve[[50, 55, 200]] = [5, 4, 3]
    cands = highlights.candidates(curve, k=3)
    spans = sorted((c.start, c.end) for c in cands)
    assert all(a[1] <= b[0] for a, b in zip(spans, spans[1:], strict=False))


def test_sections_and_channels():
    assert sources.parse_section("1:00:00-1:30:00") == (3600, 5400)
    assert sources.channel_live_url("@abc") == "https://www.youtube.com/@abc/live"
    assert sources.channel_live_url("https://www.twitch.tv/x") == "https://www.twitch.tv/x"
