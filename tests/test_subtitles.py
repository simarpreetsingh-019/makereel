from makereel.core import subtitles

SRT = """1
00:01:40,000 --> 00:01:42,000
Hello <i>there</i> friend

2
00:01:42,500 --> 00:01:44,000
how are you
"""

VTT = """WEBVTT

00:00:01.000 --> 00:00:02.000
we are live

00:00:02.000 --> 00:00:03.500
we are live
right now
"""


def test_srt_words_have_times_inside_their_cue():
    words = subtitles.cues_to_words(subtitles.parse_cues(SRT))
    assert [w["word"] for w in words] == ["Hello", "there", "friend", "how", "are", "you"]
    assert words[0]["start"] == 100 and words[2]["end"] <= 102


def test_whole_video_subtitles_move_to_the_reel_clock():
    words = subtitles.cues_to_words(subtitles.parse_cues(SRT))
    on = subtitles.on_reel_clock(words, reel_start=99, length=20)
    assert on[0]["start"] == 1 and len(on) == 6


def test_rolling_vtt_is_deduplicated():
    cues = subtitles.parse_cues(VTT)
    assert [c["text"] for c in cues] == ["we are live", "right now"]


def test_plain_text_has_no_cues_and_srt_round_trips():
    assert subtitles.parse_cues("just some words") == []
    words = [{"word": w, "start": i * 0.5, "end": i * 0.5 + 0.4} for i, w in enumerate("a b c".split())]
    back = subtitles.cues_to_words(subtitles.parse_cues(subtitles.to_srt(words)))
    assert [w["word"] for w in back] == ["a", "b", "c"]
