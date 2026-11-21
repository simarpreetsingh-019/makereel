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
    (d / "reel_01.json").write_text(json.dumps({"captions_edited": True, "source_start": 10, "captions": "reel_01.ass"}))
    monkeypatch.setattr(sources, "youtube_captions", lambda url, lang: [{"start": 10, "end": 11, "word": "x"}] * 5)
    res = library.youtube_upgrade("Live")
    assert res["updated"] == 0 and res["skipped"] == 1
    assert library.pending_youtube_upgrades() == []       # just tried: wait an hour before trying again
