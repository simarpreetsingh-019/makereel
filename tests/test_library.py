import json

import pytest

from makereel.core import captions
from makereel.errors import Forbidden, InvalidInput, NotFound
from makereel.services import library


def test_safe_name_is_portable():
    assert library.safe_name('a/b:c*d?"e<f>g|h') == "a b c d e f g h"
    assert library.safe_name("   ...  ") == "untitled"
    assert len(library.safe_name("x" * 300)) <= 80


def test_folder_for_disambiguates_same_title():
    first = library.folder_for("Same title", "id1")
    first.mkdir(parents=True)
    (first / "folder.json").write_text(json.dumps({"id": "id1"}))
    assert library.folder_for("Same title", "id1") == first
    assert library.folder_for("Same title", "id2").name == "Same title (id2)"


def test_paths_cannot_escape_library():
    with pytest.raises(Forbidden):
        library.media_file("../makereel.json")
    with pytest.raises((Forbidden, NotFound)):
        library.list_reels("../..")
    with pytest.raises(InvalidInput):
        library.get_reel("x", "../../etc")


def test_list_and_read_reel():
    d = library.root() / "My video"
    d.mkdir(parents=True)
    (d / "folder.json").write_text(json.dumps({"id": "v1", "title": "My video"}))
    (d / "reel_01.mp4").write_bytes(b"fake")
    (d / "reel_01.ass").write_text(captions.build_ass([{"start": 0, "end": 1, "word": "hi"}], 0, 2, "t"))
    (d / "reel_01.json").write_text(json.dumps({"file": "reel_01.mp4", "raw": "reel_01.raw.mp4",
                                                "captions": "reel_01.ass", "hook": "t", "start": 0, "end": 2}))
    folders = library.list_folders()
    assert folders[0]["title"] == "My video" and folders[0]["count"] == 1
    reel = library.get_reel("My video", "reel_01")
    assert reel["transcript"] == "HI"
    library.delete_reel("My video", "reel_01")
    assert not (d / "reel_01.mp4").exists()
