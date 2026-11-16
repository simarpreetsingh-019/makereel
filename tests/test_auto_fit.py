from pathlib import Path

from makereel.core import render


def _fake(monkeypatch, found):
    monkeypatch.setattr(render, "track_for", lambda src, fmt, fit, sec: found.get(fit))


def test_auto_prefers_split(monkeypatch):
    _fake(monkeypatch, {"split": "panels", "track": "crop"})
    assert render.plan_fit(Path("x"), "9x16", "auto", (0, 10)) == ("split", "panels")


def test_auto_then_track(monkeypatch):
    _fake(monkeypatch, {"track": "crop"})
    assert render.plan_fit(Path("x"), "9x16", "auto", (0, 10)) == ("track", "crop")


def test_auto_falls_back_to_blur(monkeypatch):
    _fake(monkeypatch, {})
    assert render.plan_fit(Path("x"), "9x16", "auto", (0, 10)) == ("blur", None)
