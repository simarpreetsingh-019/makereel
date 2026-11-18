"""The same live stream is recorded once, however it was started (watcher or a pasted link)."""
import json
import threading
from types import SimpleNamespace

import pytest

from makereel.errors import Conflict
from makereel.services import library
from makereel.services.jobs import JobManager


class FakeSession:
    def __init__(self, vid):
        self.info = SimpleNamespace(id=vid, url=f"https://youtu.be/{vid}", title=f"Stream {vid}")
        self.out = SimpleNamespace(name=f"Stream {vid}")
        self.stop = threading.Event()

    def run(self):
        self.stop.wait(5)

    def stats(self):
        return {"seconds": 0, "reels": 0, "chat": 0}


def test_same_stream_is_not_recorded_twice(tmp_path):
    jobs = JobManager(tmp_path / "makereel.json")
    first = jobs.adopt_live(FakeSession("abc"))
    with pytest.raises(Conflict, match="already recording"):
        jobs.adopt_live(FakeSession("abc"))
    assert jobs.recording("abc") is first
    jobs.adopt_live(FakeSession("xyz"))           # a different stream at the same time is fine
    jobs.stop_all_live()


def test_same_video_reuses_its_folder_when_title_changes():
    d = library.root() / "Live 22 31"
    d.mkdir(parents=True)
    (d / "folder.json").write_text(json.dumps({"id": "vid1"}))
    assert library.folder_for("Live 22 32", "vid1") == d
    assert library.folder_for("Live 22 32", "other") != d


def test_clear_finished_jobs_keeps_running_ones(tmp_path):
    jobs = JobManager(tmp_path / "makereel.json")
    live = jobs.adopt_live(FakeSession("run1"))
    done = jobs.adopt_live(FakeSession("run2"))
    jobs.stop(done.id)
    with pytest.raises(Conflict):
        jobs.remove(live.id)
    assert jobs.clear_finished() == 1
    assert [j["id"] for j in jobs.list()] == [live.id]
    jobs.stop_all_live()
