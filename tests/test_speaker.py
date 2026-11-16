from makereel.core import framing


def _rows(pattern, n=6):
    """pattern: list of (left_move, right_move) per second -> samples at 6 fps."""
    rows = []
    for left, right in pattern:
        rows += [([(0.15, 0.16, left), (0.8, 0.15, right)], False)] * n
    return rows


def side(x):
    return "L" if x < 0.5 else "R"


def test_starts_on_whoever_talks_not_the_bigger_face():
    out = framing.follow_speaker(_rows([(1, 15)] * 4))
    assert {side(x) for x in out} == {"R"}


def test_switches_when_the_other_person_talks():
    out = framing.follow_speaker(_rows([(15, 1)] * 4 + [(1, 15)] * 4))
    assert side(out[0]) == "L" and side(out[-1]) == "R"


def test_a_quick_yeah_does_not_move_the_camera():
    out = framing.follow_speaker(_rows([(15, 1)] * 3 + [(1, 15)] * 1 + [(15, 1)] * 3, n=3), fps=6)
    assert {side(x) for x in out} == {"L"}


def test_briefly_lost_face_keeps_the_shot():
    rows = _rows([(1, 15)] * 3)
    rows[8] = ([(0.15, 0.16, 1)], False)
    out = framing.follow_speaker(rows)
    assert side(out[8]) == "R"


def test_no_mouths_means_fallback():
    assert framing.follow_speaker([([(0.5, 0.2, None)], False)] * 10) is None


def test_switch_is_moved_back_to_when_they_started():
    out = framing.follow_speaker(_rows([(15, 1)] * 3 + [(1, 15)] * 3))
    first_r = next(i for i, x in enumerate(out) if side(x) == "R")
    assert first_r <= 3 * 6 + 2                 # within ~0.3 s of the real change at 3 s


def test_wide_shot_kept_and_zooms(monkeypatch):
    from pathlib import Path

    from makereel.core import framing, render
    monkeypatch.setattr(framing, "_dimensions", lambda v: (1620, 1080))
    shots = framing.clean_shots([{"start": 0, "x": 0.75}, {"start": 2, "x": 0.5, "wide": 1}, {"start": 5, "x": 0.25}])
    assert shots[1]["wide"] is True and "wide" not in shots[0]
    assert framing.shift_shots(shots, 3, 10)[0]["wide"] is True
    crop = framing.crop_from_shots(Path("x.mp4"), shots, 1080, 1920)
    assert crop.zoom is not None
    f = render.reframe_filter("9x16", "track", crop, 30)
    assert "eval=frame" in f and "overlay" in f
    plain = framing.crop_from_shots(Path("x.mp4"), [{"start": 0, "x": 0.3}], 1080, 1920)
    assert plain.zoom is None
