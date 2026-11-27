import json

import pytest

from backend.core import budget, dubbing, isochron, jobs, pipeline, shorten, translate
from backend.core.subtitles import Cue
from training.prepare_dialogue import prepare, read_jsonl, split_reviewed, terms, write_reviewed_splits
from training.train_nllb_lora import build_examples, load_pairs


def test_export_uses_separate_approved_subtitle_and_spoken_script(studio_client, workdir, monkeypatch):
    monkeypatch.setattr(jobs, "JOB_DIR", workdir)
    monkeypatch.delenv("VSUB_SPOKEN_ADAPTER", raising=False)
    original = "Bởi vì tôi rất là mệt nhé."
    rows = [Cue(0, .45, "I'm tired.", original, speaker="A").to_dict(),
            Cue(.46, 3, "Rest.", "Nghỉ đi.", speaker="B").to_dict()]
    state = {"cues": rows, "target_lang": "vi", "source_lang": "en", "video_path": "synthetic.mp4",
             "video_name": "studio", "info": {"duration": 3}}
    preview = studio_client.post("/api/tts/script", json={"cues": rows, "target_lang": "vi", "shorten": True})
    base = preview.json()["units"][0]["text"]
    assert base != original
    cfg = {"outputs": {"srt": True, "vtt": True, "dub": True}, "display": "second",
           "dub": {"shorten": True, "script": [{"base": base, "cues": [0], "text": "Tôi mệt quá."}]}}
    voice = []

    def record(job, cues, state, cfg, *args):
        units = dubbing.speech_units(cues)
        assert units[0]["text"] == base
        assert dubbing.apply_script(units, cfg["dub"]["script"]) == 1
        voice.extend(u["text"] for u in units)

    monkeypatch.setattr(pipeline, "_run_dub", record)
    job = jobs.Job("render-test", "render", steps=pipeline.render_steps(cfg))
    pipeline.run_render(job, state, cfg)
    assert voice == ["Tôi mệt quá.", "Nghỉ đi."]
    assert state["cues"][0]["text2"] == original
    for name in ("studio.vi.srt", "studio.vi.vtt", "burn.ass"):
        assert original in (job.dir / name).read_text(encoding="utf-8")


@pytest.mark.parametrize("original,bad", [
    ("Minh không định trả lại hai vé.", "Lan không trả hai vé."),
    ("Nếu chị đến trễ thì tôi sẽ đợi.", "Chị đến, tôi sẽ đợi."),
    ("Tôi còn phải đợi 15 ngày nữa.", "Tôi phải đợi 15 giờ."),
    ("Anh trả lại hai vé cho tôi nhé.", "Anh trả ba vé cho tôi."),
    ("Chúng ta sẽ nghỉ ở đây.", "Ta sẽ nghỉ đây."),
    ("Anh đã gặp bà chưa?", "Anh gặp bà chưa."),
    ("Nhiệt độ ở đây là -5 độ.", "Nhiệt độ là 5 độ."),
])
def test_veto_changes_of_meaning(original, bad):
    assert budget._shorter_line(original, bad) == original


@pytest.mark.parametrize("line", ["Tôi cần một cách khác.", "Đáp án là một.", "Chúng ta sẽ về.", "Tàu đang chạy."])
def test_rules_do_not_erase_meaning_to_meet_a_cap(line):
    assert shorten.shorten(line, 1)[0] == line


def test_editorial_choices_survive_automatic_fit(monkeypatch):
    monkeypatch.setattr(translate, "engine_available", lambda *a: (True, ""))
    monkeypatch.setattr(translate, "_translate_deep", lambda texts, *a: ["Bản máy"] * len(texts))
    monkeypatch.setattr(translate, "_recall", lambda *a: ({0: "Tôi chờ ở ga phía đông."}, []))
    cues = [Cue(0, .1, "I'll wait."), Cue(.11, .25, "Which gate?"), Cue(.26, .5, "OK.")]
    translate.translate_cues(cues, "en", "vi", glossary="Which gate? = Cổng nào mở lúc sáu giờ?")
    old = [c.text2 for c in cues]
    sent = []
    budget.run_loop(cues, lambda rows: sent.extend(r["source"] for r in rows) or [r["text"] for r in rows])
    assert old[:2] == ["Tôi chờ ở ga phía đông.", "Cổng nào mở lúc sáu giờ?"]
    assert [c.text2 for c in cues] == old
    assert not {"I'll wait.", "Which gate?"}.intersection(sent)


def test_task_routing_and_incomplete_candidates(workdir, monkeypatch):
    path = workdir
    meta = {"base_model": "facebook/nllb-200-distilled-600M", "src_lang": "vi", "task": "spoken", "finished": False}
    for filename in ("adapter_config.json", "adapter_model.safetensors"):
        (path / filename).touch()
    monkeypatch.setenv("VSUB_SPOKEN_ADAPTER", str(path))
    def save():
        (path / "train_meta.json").write_text(json.dumps(meta), encoding="utf-8")
    save()
    assert "spoken_vi" not in isochron.dialogue_adapters()
    meta["finished"] = True
    save()
    assert isochron.dialogue_adapters()["spoken_vi"] == path
    loaded = ("zh", "meaning_zh", "spoken_vi")
    monkeypatch.setattr(translate, "lora_langs", lambda: ["zh"])
    assert translate._adapter_plan(loaded, "zh", "vi") == ("meaning_zh", False)
    assert translate._adapter_plan(loaded, "zh", "vi", budgeted=True) == ("zh", False)
    assert translate._adapter_plan(loaded, "en", "vi") == (None, True)
    assert translate._adapter_plan(loaded, "vi", "vi", spoken=True) == ("spoken_vi", False)
    with pytest.raises(translate.TranslateError):
        translate._adapter_plan(("zh",), "vi", "vi", spoken=True)


def test_spoken_model_gets_the_approved_vietnamese_not_the_source(monkeypatch):
    monkeypatch.delenv("VSUB_NLLB_LORA", raising=False)
    monkeypatch.setattr(isochron, "dialogue_adapters", lambda: {"spoken_vi": True})
    rows = [{"text": "Anh hãy mang cái túi màu đỏ về nhà.", "target_syllables": 6, "source": "unused"},
            {"text": "Minh chưa hề trả 12 vé.", "target_syllables": 4, "source": "unused"}]

    def candidate(texts, src, tgt, *, budgets, spoken, on_log):
        assert texts == [r["text"] for r in rows] and budgets == [6, 4]
        assert (src, tgt, spoken) == ("vi", "vi", True)
        return ["Anh mang túi đỏ về nhà.", "Minh trả 12 vé."]

    monkeypatch.setattr(translate, "_translate_nllb", candidate)
    assert translate.spoken_tightener()(rows) == ["Anh mang túi đỏ về nhà.", rows[1]["text"]]


def test_prepare_uses_reviewed_pairs_and_excludes_holdout_on_both_sides():
    locked = {"src": "明天下雨。", "tgt": "Ngày mai sẽ mưa.", "spoken": "Mai sẽ mưa."}
    approved = {"src": "明天开门。", "src_lang": "zh", "tgt_lang": "vi",
                "tgt": "Cửa sẽ mở vào ngày mai.", "spoken": "Mai cửa sẽ mở."}
    pairs = [("明天下雨!", "Mai trời sẽ mưa."), ("天要下雨了", "Mai sẽ mưa!"), ("大家休息", "Mọi người nghỉ đi.")]
    mt, speech = prepare(pairs, "zh", [approved], [locked], 50, 0)
    assert mt[0]["src"] == approved["src"] and mt[0]["tgt"] == approved["tgt"]
    assert speech[0]["src"] == approved["tgt"] and speech[0]["tgt"] == approved["spoken"]
    assert all(r["src_lang"] == "vi" for r in speech)
    for rows in (mt, speech):
        assert not any(terms(r) & terms(locked) for r in rows)


def test_grouped_training_excludes_other_films_and_both_vietnamese_variants(workdir):
    films = ["delta", "harbor", "hill", "loft", "lake"]
    rows = [{"film": film, "src_lang": "zh", "tgt_lang": "vi", "src": f"{film} source", "tgt": f"{film} subtitle",
             "spoken": f"{film} speech", "cap": 7} for film in films]
    # Same spoken reference in different films, despite distinct foreign originals.
    duplicate = [dict(r, src=r["src"]+"2", tgt=r["tgt"]+"2", spoken="Same line.") for r in rows]
    extra = dict(rows[0], src="new row", tgt="reserved reference!", spoken="other wording")
    splits = split_reviewed(rows + duplicate + [extra], "zh", protected=[{"tgt": "Reserved reference"}])
    assert sum(map(len, splits.values())) == 6
    assert all(r["src"] != "new row" for group in splits.values() for r in group)
    for left, right in (("train", "dev"), ("train", "test"), ("dev", "test")):
        assert {r["film"] for r in splits[left]}.isdisjoint(r["film"] for r in splits[right])
        assert set().union(*(terms(r) for r in splits[left])).isdisjoint(set().union(*(terms(r) for r in splits[right])))
    out = workdir / "groups"
    write_reviewed_splits(out, splits, "zh")
    assert [r["tgt"] for r in read_jsonl(out / "spoken_dev.jsonl")] == [r["spoken"] for r in splits["dev"]]
    pairs = load_pairs(out / "spoken_train.jsonl", {"reviewed"}, 0, 42, "vi")
    assert all(x["src"].startswith("<len:7> ") for x in build_examples(pairs, 0, 42))
    assert all("<len:" not in x["src"] for x in build_examples(pairs, 1, 42))
    with pytest.raises(FileExistsError):
        write_reviewed_splits(out, splits, "zh")
    with pytest.raises(ValueError, match="three distinct films"):
        split_reviewed(rows[:2], "zh")
