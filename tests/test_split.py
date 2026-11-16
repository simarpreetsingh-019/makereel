from makereel.core import framing, render


def test_two_people_side_by_side_is_a_duo():
    samples = [[(0.28, 0.4, 0.09), (0.72, 0.42, 0.1)] for _ in range(20)]
    plan = framing.split_plan(samples)
    assert plan["kind"] == "duo"
    assert plan["people"][0][0] < 0.5 < plan["people"][1][0]


def test_small_still_face_is_a_facecam():
    samples = [[(0.88, 0.82, 0.05)] for _ in range(20)]
    plan = framing.split_plan(samples)
    assert plan["kind"] == "facecam"


def test_one_moving_big_face_is_no_split():
    samples = [[(0.3 + i * 0.02, 0.4, 0.2)] for i in range(20)]
    assert framing.split_plan(samples) is None
    assert framing.split_plan([[] for _ in range(20)]) is None


def test_panels_fill_the_reel_and_stay_in_frame():
    for plan in ({"kind": "duo", "people": [(0.25, 0.4, 0.1), (0.75, 0.4, 0.1)]},
                 {"kind": "facecam", "face": (0.9, 0.85, 0.05)}):
        panels = framing.split_panels(plan, 1280, 720, 1080, 1920)
        assert sum(ph for _, ph in panels) == 1920
        for (x, y, cw, ch), _ in panels:
            assert x >= 0 and y >= 0 and x + cw <= 1280 and y + ch <= 720


def test_split_filter_stacks_panels_and_falls_back():
    panels = [((0, 0, 600, 530), 960), ((600, 0, 600, 530), 960)]
    f = render.reframe_filter("9x16", "split", panels)
    assert "vstack=inputs=2" in f and f.endswith("[v]")
    assert "boxblur" in render.reframe_filter("9x16", "split", None)
