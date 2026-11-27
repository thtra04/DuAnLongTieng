"""Regression cases for missing speech, turn boundaries and timed edits."""

from types import SimpleNamespace
import wave

import numpy as np
import pytest

from backend.core import asr, budget, diarize, dubbing, subtitles, translate
from backend.core.subtitles import Cue


def test_short_voiced_gap_recovered_at_absolute_time(workdir, monkeypatch):
    from faster_whisper import vad

    path = workdir / "mix.wav"
    with wave.open(str(path), "wb") as wav:
        wav.setparams((1, 2, 16000, 0, "NONE", ""))
        wav.writeframes(bytes(65 * 32000))

    def seg(a, b, text):
        return SimpleNamespace(start=a, end=b, text=text, words=[SimpleNamespace(start=a, end=b, word=text)])

    clips = []

    def decode(audio, **kw):
        info = SimpleNamespace(language="en", duration=65)
        if isinstance(audio, np.ndarray):
            clips.append(len(audio))
            got = [seg(0, 1, "Wait!")] if len(clips) == 1 else []
        else:
            got = [seg(0, 10, "Before."), seg(12, 40, "Middle."), seg(42, 65, "End.")]
        return iter(got), info

    monkeypatch.setattr(asr, "load_model", lambda *a, **k: (SimpleNamespace(transcribe=decode), "cpu"))
    monkeypatch.setattr(vad, "get_speech_timestamps", lambda audio, opts: [{"start": 8000, "end": 24000}])
    r = asr.transcribe(str(path), language="en", duration=65)
    assert clips == [16000, 16000]
    assert (r["words"][1]["word"], r["words"][1]["start"], r["words"][1]["end"]) == ("Wait!", 10.5, 11.5)
    assert r["coverage"] == 1 and r["speech_gaps"] == [(40.5, 41.5)]
    assert asr.looks_like_speech({"text": "Amara, please don't subscribe to that."})


def test_two_turns_in_one_whisper_segment_survive_translation_and_dub(monkeypatch):
    words = [{"word": "Don't", "start": 0, "end": 0.5, "seg": 0},
             {"word": " leave", "start": 0.5, "end": 1, "seg": 0},
             {"word": " I won't", "start": 1, "end": 1.8, "seg": 0}]
    cues = subtitles.cues_from_words(words)
    diarize.assign(cues, [{"start": 0, "end": 1, "speaker": "S1"}, {"start": 1, "end": 2, "speaker": "S2"}])
    tr = {"Don't leave": "Đừng đi", "I won't": "Tôi không đi đâu"}
    monkeypatch.setattr(translate, "_translate_deep", lambda texts, *args: [tr[t] for t in texts])
    translate.translate_cues(cues, "en", "vi", use_memory=False)
    assert [(c.start, c.end, c.speaker, c.text2) for c in cues] == [
        (0, 1, "S1", "Đừng đi"), (1, 1.8, "S2", "Tôi không đi đâu")]
    reloaded = [Cue.from_dict(c.to_dict()) for c in cues]
    assert [(u["cues"], u["start"], u["text"]) for u in dubbing.speech_units(reloaded)] == [
        ([0], 0, "Đừng đi."), ([1], 1, "Tôi không đi đâu.")]


def test_missing_ai_ids_retried_without_overwriting_other_lines(monkeypatch, workdir):
    prompts = []

    def reply(**kw):
        prompts.append(kw["messages"][-1]["content"])
        raw = "4|Bốn\n2|Hai" if len(prompts) == 1 else "2|Sai dòng\n3|Ba"
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=raw))])

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=reply)))
    monkeypatch.setattr(translate, "_openai_client", lambda *a, **k: client)
    monkeypatch.setattr(translate, "engine_available", lambda *a: (True, ""))
    monkeypatch.setattr(translate, "_CACHE_FILE", workdir / "cache.json")
    cues = [Cue(i, i + 0.8, t) for i, t in enumerate(["One", "two", "three", "four"])]
    translate.translate_cues(cues, "en", "vi", engine="openai", auto_context=False, use_memory=False)
    assert [c.text2 for c in cues] == ["", "Hai", "Ba", "Bốn"]
    assert "1|One" in prompts[1] and "3|three" in prompts[1] and "2|two" not in prompts[1]
    assert not translate._CACHE_FILE.exists()


@pytest.mark.parametrize("bad", ["Trả 20 vé.", "Không trả 2 vé."])
def test_do_not_shorten_away_negation_or_numbers(bad):
    cues = [Cue(0, 0.45, "Don't return 20 tickets.", "Không được trả lại cả 20 vé."), Cue(0.46, 1, "Yes.", "Vâng.")]
    old = cues[0].text2
    stats = budget.run_loop(cues, lambda requests: [bad] * len(requests))
    assert cues[0].text2 == old and stats["over_after"] and not stats["tightened"]


def test_continuation_merged_before_mt_but_not_across_speakers():
    def fragments(who):
        return [Cue(2, 3, "You promised to", speaker="A", words=[{"seg": 0}]),
                Cue(3, 4, "wait for me.", speaker=who, words=[{"seg": 1}])]

    out = subtitles.join_continuations(fragments("A"), 84, 6)
    assert [(c.start, c.end, c.text) for c in out] == [(2, 4, "You promised to wait for me.")]
    assert len(subtitles.join_continuations(fragments("B"), 84, 6)) == 2


def test_thai_without_spaces_does_not_impose_one_word_translation():
    cue = Cue(10, 16, "แม่เป็นยังไงบ้าง", "Mẹ thấy trong người thế nào?")
    assert budget.line_target(cue) is None
