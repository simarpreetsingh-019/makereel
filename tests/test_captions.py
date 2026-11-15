from makereel.core import captions

WORDS = [{"start": 10.0 + i, "end": 10.5 + i, "word": w} for i, w in enumerate("hello there big world".split())]


def make():
    return captions.build_ass(WORDS, 10.0, 15.0, "Big title")


def test_round_trip_words():
    words = captions.parse_words(make())
    assert [w["word"] for w in words] == ["HELLO", "THERE", "BIG", "WORLD"]
    assert words[0]["start"] == 0.0 and words[3]["start"] == 3.0


def test_same_word_count_keeps_timing():
    ass = captions.rebuild(make(), "HELLO THERE GTA WORLD", "Big title")
    words = captions.parse_words(ass)
    assert [w["word"] for w in words] == ["HELLO", "THERE", "GTA", "WORLD"]
    assert [w["start"] for w in words] == [0.0, 1.0, 2.0, 3.0]


def test_different_word_count_spreads_evenly():
    words = captions.parse_words(captions.rebuild(make(), "one two", None))
    assert [w["word"] for w in words] == ["ONE", "TWO"]
    assert words[0]["start"] == 0.0 and words[1]["start"] > words[0]["start"]


def test_rebuild_keeps_custom_styles():
    custom = make().replace("Arial Black,86", "Impact,90")
    assert "Impact,90" in captions.rebuild(custom, "a b c d", "x")


def test_set_hook():
    assert ",,NEW ONE\n" in captions.set_hook(make(), "new one")


def test_braces_are_stripped_from_words():
    ass = captions.build_ass([{"start": 0, "end": 1, "word": "{evil}"}], 0, 2, None)
    assert "{evil}" not in ass
