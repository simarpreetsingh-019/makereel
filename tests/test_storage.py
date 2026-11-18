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


def test_status_and_help_run(capsys):
    from makereel import cli
    cli.main(["help"])
    assert "makereel start" in capsys.readouterr().out
    cli.main(["status"])
    out = capsys.readouterr().out
    assert "makereel isn't running" in out and "Speech models" in out
