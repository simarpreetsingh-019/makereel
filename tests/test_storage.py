"""Choosing where files are saved, moving reels, and clearing the cache."""
import pytest

from makereel import config
from makereel.errors import ConfigError
from makereel.services import storage


@pytest.fixture
def no_env_folders(monkeypatch):
    monkeypatch.delenv("MAKEREEL_OUTPUT_DIR")
    monkeypatch.delenv("MAKEREEL_WORK_DIR")
    config._env_cache = None


def test_folder_setting_and_env_precedence(tmp_path, no_env_folders, monkeypatch):
    assert config.reels_dir().name == "output"                         # default
    config.save_settings({"reels_folder": str(tmp_path / "Reels")})
    assert config.reels_dir() == tmp_path / "Reels"
    monkeypatch.setenv("MAKEREEL_OUTPUT_DIR", str(tmp_path / "env"))  # the environment wins
    config._env_cache = None
    assert config.reels_dir() == tmp_path / "env"
    with pytest.raises(ConfigError, match="full path"):
        config.save_settings({"reels_folder": "relative/path"})


def test_move_existing_reels(tmp_path, no_env_folders):
    old = config.reels_dir()
    (old / "Video A").mkdir(parents=True)
    (old / "Video A" / "reel_01.mp4").write_bytes(b"x")
    res = storage.move_reels(str(tmp_path / "New"), move_existing=True)
    assert res["moved"] == 1 and (tmp_path / "New" / "Video A" / "reel_01.mp4").exists()


def test_clear_cache_keeps_live_recordings(tmp_path):
    work = config.work_dir()
    (work / "live_abc").mkdir(parents=True)
    (work / "live_abc" / "s1_000001.ts").write_bytes(b"x" * 1000)
    (work / "live_old").mkdir()
    (work / "live_old" / "s1_000001.ts").write_bytes(b"x" * 2000)
    (work / "uploads").mkdir()
    (work / "uploads" / "big.mp4").write_bytes(b"x" * 3000)
    res = storage.clear_cache(recording={"abc"})
    assert res["kept"] == ["live_abc"] and res["freed_bytes"] == 5000
    assert (work / "live_abc").exists() and not (work / "live_old").exists() and not (work / "uploads").exists()


def test_status_and_help_run(capsys, monkeypatch):
    from makereel import cli, config
    monkeypatch.setenv("MAKEREEL_PORT", "8899")          # a port nothing listens on: "not running"
    config._env_cache = None
    cli.main(["help"])
    assert "makereel start" in capsys.readouterr().out
    cli.main(["status"])
    out = capsys.readouterr().out
    assert "makereel isn't running" in out and "Speech models" in out


def test_folder_zip_has_reels_and_post_text(tmp_path):
    import json
    import zipfile

    from makereel import config
    from makereel.services import library
    d = config.reels_dir() / "Video A"
    d.mkdir(parents=True)
    (d / "reel_01.mp4").write_bytes(b"video")
    (d / "reel_01.json").write_text(json.dumps({"file": "reel_01.mp4", "caption": "Credit: someone"}))
    res = library.folder_zip("Video A")
    assert res["count"] == 1 and "download=1" in res["download"]
    with zipfile.ZipFile(d / "all-reels.zip") as z:
        assert sorted(z.namelist()) == ["reel_01.mp4", "reel_01.txt"]
        assert z.read("reel_01.txt").decode().startswith("Credit: someone")


def test_job_stage_from_log():
    from makereel.services.jobs import Job
    j = Job("link", "u")
    assert j._stage() is None
    j.append_log("12:00 [2/3] transcribing 3 candidate windows")
    assert j._stage() == {"step": 2, "label": "transcribing 3 candidate windows"}


def test_youtube_upgrade_skips_hand_edited_reels(monkeypatch):
    import json

    from makereel import config
    from makereel.core import sources
    from makereel.services import library
    d = config.reels_dir() / "Live"
    d.mkdir(parents=True)
    (d / "folder.json").write_text(json.dumps({"url": "https://www.youtube.com/watch?v=x", "live_status": "is_live"}))
    post = {"captions_edited": True, "source_start": 10, "captions": "reel_01.ass"}
    (d / "reel_01.json").write_text(json.dumps(post))
    monkeypatch.setattr(sources, "youtube_captions", lambda url, lang: [{"start": 10, "end": 11, "word": "x"}] * 5)
    res = library.youtube_upgrade("Live")
    assert res["updated"] == 0 and res["skipped"] == 1
    assert library.pending_youtube_upgrades() == []       # just tried: wait an hour before trying again


def test_creator_memory_and_suggestions():
    import json

    from makereel import config
    from makereel.services import creators
    for i, words in enumerate(["bhai Lucia aaja", "Lucia kidhar hai bhai", "Pinky gaadi"]):
        d = config.reels_dir() / f"Stream {i}"
        d.mkdir(parents=True)
        (d / "folder.json").write_text(json.dumps({"channel": "Mythpat"}))
        (d / "reel_01.ass").write_text("[Events]\\nDialogue: 0,0:00:00.00,0:00:02.00,Caption,,0,0,0,," + words + "\\n")
    assert creators.channels() == ["Mythpat"]
    saved = creators.save("Mythpat", ["Vice City", " "], "GTA in Hinglish")
    assert saved["names"] == ["Vice City"] and creators.load("Mythpat")["notes"] == "GTA in Hinglish"


def test_youtube_captions_check_only_keeps_makereel_captions(monkeypatch):
    import json

    from makereel import config
    from makereel.core import captions, sources
    from makereel.services import library
    config.save_settings({"clip": {"youtube_captions": "check"}})
    d = config.reels_dir() / "Live2"
    d.mkdir(parents=True)
    (d / "folder.json").write_text(json.dumps({"url": "https://www.youtube.com/watch?v=x", "recorded_live": True}))
    words = [{"start": 10 + i, "end": 10.5 + i, "word": w} for i, w in enumerate(["hello", "there", "big", "world"])]
    ass = captions.build_ass(words, 10.0, 15.0, "Title")
    (d / "reel_01.ass").write_text(ass)
    (d / "reel_01.json").write_text(json.dumps({"source_start": 10, "captions": "reel_01.ass", "length": 5}))
    yt = [{"start": 10 + i, "end": 10.5 + i, "word": w} for i, w in enumerate(["hello", "there", "bug", "world"])]
    monkeypatch.setattr(sources, "youtube_captions", lambda url, lang: yt)
    res = library.youtube_upgrade("Live2")
    assert res["updated"] == 1 and res["status"].startswith("Checked")
    post = json.loads((d / "reel_01.json").read_text())
    check = post["caption_check"]
    assert check["checker"] == "YouTube's captions" and "bug" in [w["word"] for w in check["other"]]
    assert "captions_source" not in post and (d / "reel_01.ass").read_text() == ass     # captions untouched
    assert library.youtube_upgrade("Live2")["updated"] == 0                           # not checked twice


def test_youtube_captions_setting_values():
    from makereel import config
    for given, want in ((True, "use"), (False, "off"), ("check", "check"), ("junk", "use")):
        clip = {**config.CLIP_DEFAULTS, "youtube_captions": given}
        config.validate_clip(clip)
        assert clip["youtube_captions"] == want


def test_compare_with_pasted_script():
    import json

    from makereel import config
    from makereel.core import captions
    from makereel.services import library
    d = config.reels_dir() / "Paste"
    d.mkdir(parents=True)
    words = [{"start": 10 + i, "end": 10.5 + i, "word": w} for i, w in enumerate(["bas", "do", "minute", "bache"])]
    (d / "reel_01.ass").write_text(captions.build_ass(words, 10.0, 15.0, "T"))
    (d / "reel_01.json").write_text(json.dumps({"captions": "reel_01.ass", "length": 5, "file": "reel_01.mp4"}))
    (d / "reel_01.mp4").write_bytes(b"x")
    library.compare_with_text("Paste", "reel_01", "bas two minute left", "English")
    post = json.loads((d / "reel_01.json").read_text())
    assert post["caption_check"]["checker"] == "English text"
    rows = library._compare(post, captions.parse_words((d / "reel_01.ass").read_text()))["rows"]
    assert [r["ok"] for r in rows] == [True, False, True, False]        # lined up by word order


def test_bulk_english_letters_picks_the_right_reels():
    import json

    from makereel import config
    from makereel.core import captions
    from makereel.services import library
    d = config.reels_dir() / "Bulk"
    d.mkdir(parents=True)
    for name, word, check, edited in (("reel_01", "भाई", "hinglish", False), ("reel_02", "bhai", None, False),
                                      ("reel_03", "भाई", "hinglish", True)):
        ass = captions.build_ass([{"start": 10, "end": 11, "word": word}], 10.0, 12.0, "T")
        (d / f"{name}.ass").write_text(ass, encoding="utf-8")
        post = {"captions": f"{name}.ass", "captions_edited": edited}
        if check:
            post["caption_check"] = {"checker": check, "other": [{"start": 0, "word": "bhai"}]}
        (d / f"{name}.json").write_text(json.dumps(post))
    assert [n for _, n in library._bulk_targets("convert")] == ["reel_01", "reel_03"]   # still in हिंदी letters
    assert [n for _, n in library._bulk_targets("hinglish")] == ["reel_01"]             # hand edits kept


def test_english_letters_prefers_a_downloaded_hinglish_model(monkeypatch):
    from makereel.core import models, transcribe
    monkeypatch.setattr(models, "installed", lambda name: name == "hinglish")
    assert transcribe.model_for("base", "hi", "small", "roman") == "hinglish"
    assert transcribe.model_for("base", "hi", "small", "original") != "hinglish"
    assert transcribe.model_for("base", "en", "small", "roman") == "base"


def test_live_timeline_buckets_and_moments():
    import collections

    from makereel.core import live
    s = object.__new__(live.LiveSession)
    s.db = [-30.0] * 100 + [-10.0] * 20
    s.chat = collections.Counter({101: 4, 102: 3})
    s.heard = [{"t": 103, "word": "OMG"}]
    s.moments = [{"t": 101.0, "why": ["loud"], "reel": True}]
    s.made, s.per_hour = [1.0], 6
    d = s.timeline(minutes=5, step=10)
    assert d["seconds"] == 120 and len(d["buckets"]) == 12
    b = next(x for x in d["buckets"] if x["t"] == 100)
    assert b["loud"] == -10.0 and b["chat"] == 7
    assert d["moments"][0]["reel"] is True and d["reels"] == 1


def test_onnx_tokens_become_timed_words():
    from makereel.core import transcribe
    words = transcribe.tokens_to_words([" ब", "स", " दो", "▁hi", "ya"], [0.8, 0.9, 1.1, 1.5, 1.6], offset=10)
    assert [w["word"] for w in words] == ["बस", "दो", "hiya"]
    assert words[0]["start"] == 10.8 and words[0]["end"] == 11.1 and words[-1]["end"] == 11.9


def test_indic_model_only_for_hindi(monkeypatch):
    from makereel.core import transcribe
    monkeypatch.setattr(transcribe, "_downloaded_multilingual", lambda: "medium")
    assert transcribe.model_for("base", "hi", "indic-hi") == "indic-hi"
    assert transcribe.model_for("base", "ta", "indic-hi") == "medium"     # Tamil: not a Hindi model
    assert transcribe.model_for("parakeet", "hi", "small") == "small"     # English-only model can't do Hindi
