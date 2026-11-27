import io
import json
import wave

import numpy as np
import pytest

from backend.api import jobs as job_api
from backend.core import dub_review, dubbing, jobs
from backend.core.subtitles import Cue
from backend.store import projects


@pytest.fixture
def scene(workdir, monkeypatch):
    for module in (projects, job_api, jobs):
        monkeypatch.setattr(module, "JOB_DIR", workdir)
    folder = workdir / "scene"
    folder.mkdir()
    video = folder / "source.mp4"
    video.touch()
    rows = [Cue(0, 2, "Hi.", "Chào anh.", "S1").to_dict(),
            Cue(2, 4, "Bye.", "Tạm biệt.", "S2").to_dict()]
    state = {"cues": rows, "video_name": "scene.mp4", "video_path": str(video),
             "source_lang": "en", "target_lang": "vi", "info": {"duration": 4}}
    (folder / "state.json").write_text(json.dumps(state), encoding="utf-8")
    return folder, {"project": "scene", "cues": rows, "source_lang": "en", "target_lang": "vi"}


def voice(monkeypatch, synth):
    class Engine:
        def infer(self, text, **kw):
            return synth(text, kw)
    monkeypatch.setattr(dubbing, "available", lambda: (True, ""))
    monkeypatch.setattr(dubbing, "list_voices", lambda: [{"id": "A", "label": "Test"}])
    monkeypatch.setattr(dubbing, "get_engine", Engine)


def tone():
    return .2 * np.sin(np.arange(dubbing.SR // 2) * .02)


def test_review_covers_every_line_including_silent_and_partially_translated():
    cues = [Cue(0, 1, "Hello", "Chào"), Cue(1, 2, "What?"), Cue(2, 3, "Door", "Cửa 门"), Cue(3, 4, "End", "...")]
    draft = dub_review.draft(cues, "scene", "en", "vi")
    assert [it["cue"] for it in draft["issues"]] == [1, 2, 3]
    assert [u["cues"] for u in draft["units"]] == [[0], [1], [2], [3]]
    assert draft["units"][1]["text"] == ""
    with pytest.raises(ValueError, match="#2"):
        dub_review.approved(cues, draft, "scene", "en", "vi", False)


def test_project_review_keeps_adjacent_lines_of_the_same_speaker_on_their_own_marks():
    cues = [Cue(15.1, 16.8, "锦衣玉食", "Đồ ăn và quần áo sang trọng", "S1"),
            Cue(16.8, 18.6, "好大的口气", "Thật là một giai điệu lớn", "S1")]
    assert len(dubbing.speech_units(cues)) == 1
    draft = dub_review.draft(cues, "scene", "zh", "vi")
    units = dub_review.approved(cues, draft, "scene", "zh", "vi", False)
    assert [(u["start"], u["text"]) for u in units] == [(c.start, c.text2 + ".") for c in cues]
    assert not any(c.pinned for c in cues)


def test_source_only_english_and_simultaneous_starts_are_not_ready_to_dub():
    cues = [Cue(0, 1, "First"), Cue(0, 2, "Second")]
    assert all("Thiếu bản dịch" == i["reason"] for i in dub_review.draft(cues, "scene", "en")["issues"])
    cues[0].text2, cues[1].text2 = "Một.", "Hai."
    draft = dub_review.draft(cues, "scene", "en", "vi")
    assert draft["issues"][0]["field"] == "start"
    with pytest.raises(ValueError, match="#1.*#2"):
        dub_review.approved(cues, draft, "scene", "en", "vi", False)


def test_approval_atomically_saves_subtitle_draft_and_rejects_concurrent_approval(scene, studio_client):
    _, data = scene
    url = "/api/projects/scene/dub-review"
    old = projects.full("scene")
    data["cues"][1]["text2"] = "Hẹn mai nhé."
    draft = studio_client.post("/api/tts/script", json=data).json()
    draft["units"][1]["text"] = "Hẹn ngày mai."
    req = {**data, "review": draft, "revision": old["revision"]}
    result = studio_client.post(url, json=req)
    assert result.is_success
    current = projects.full("scene")
    assert current["revision"] == result.json()["revision"] != old["revision"]
    assert current["cues"][1]["text2"] == "Hẹn mai nhé."
    assert current["dub_review"]["units"][1]["text"] == "Hẹn ngày mai."
    draft["units"][1]["text"] = "Đừng áp bản cũ."
    assert studio_client.post(url, json=req).status_code == 409
    assert projects.full("scene")["dub_review"] == current["dub_review"]


def test_only_the_saved_approved_words_reach_tts_and_script_file(scene, studio_client, monkeypatch):
    folder, data = scene
    render = "/api/jobs/scene/render"
    cfg = {"outputs": {"dub": True, "srt": True}, "display": "second", "learn": False,
           "dub": {"voice": "A", "voices": {"S1": "A", "S2": "A"}, "original_mode": "mute", "auto_level": False}}
    original = (folder / "state.json").read_bytes()
    assert studio_client.post(render, json=cfg).status_code == 409
    assert (folder / "state.json").read_bytes() == original
    draft = studio_client.post("/api/tts/script", json=data).json()
    approve = "/api/projects/scene/dub-review"
    assert studio_client.post(approve, json={**data, "review": {**draft, "units": draft["units"][:1]}}).status_code == 422
    draft["units"][0]["text"] = "Chào cả nhà!"
    ok = studio_client.post(approve, json={**data, "review": draft})
    assert ok.is_success, ok.text
    token = ok.json()["token"]
    assert projects.full("scene")["dub_review"]["token"] == token
    cfg["dub"].update(approved_script=token, script=[{"cues": [0], "text": "Wrong!"}])
    for field, value in (("speaker", "S7"), ("text2", "Sửa sau khi duyệt"), ("end", 1.3)):
        stale = [{**data["cues"][0], field: value}, data["cues"][1]]
        assert studio_client.post(render, json={**cfg, "cues": stale}).status_code == 409
    read = []
    voice(monkeypatch, lambda text, kw: read.append(text) or tone())
    monkeypatch.setattr(job_api, "run_in_thread", lambda job, target: target(job))
    monkeypatch.setattr(dubbing, "mux_dub", lambda video, wav, dst, **kw: dst.touch())
    result = studio_client.post(render, json=cfg)
    assert result.is_success, result.text
    job = jobs.get_job(result.json()["job_id"])
    assert read == ["Chào cả nhà!", "Tạm biệt."]
    assert job.result["dub_stats"]["count"] == 2
    assert read[0] in (job.dir / "scene.kichban.txt").read_text(encoding="utf-8")
    assert "Chào anh." in (job.dir / "scene.vi.srt").read_text(encoding="utf-8-sig")
    changed = [{**data["cues"][0], "text2": "Lời mới."}, data["cues"][1]]
    assert studio_client.put("/api/projects/scene/cues", json={"cues": changed}).is_success
    assert studio_client.post(render, json={**cfg, "cues": data["cues"]}).status_code == 409
    assert projects.full("scene")["cues"] == changed


def test_audition_reads_one_unsaved_unit_without_committing_or_rendering(scene, studio_client, monkeypatch):
    folder, data = scene
    before = (folder / "state.json").read_bytes()
    seen = []
    voice(monkeypatch, lambda text, kw: seen.append((text, kw)) or tone())
    data["cues"][1]["start"] = 2.25
    payload = {**data, "unit": {"cues": [1], "text": "Hẹn gặp lại!"}, "offset": .25, "voice": "A", "style": "doc_truyen"}
    r = studio_client.post("/api/projects/scene/dub-preview", json=payload)
    assert r.is_success, r.text if not r.is_success else ""
    assert float(r.headers["x-preview-start"]) == 2.5 and "no-store" in r.headers["cache-control"]
    with wave.open(io.BytesIO(r.content)) as wav:
        assert 0 < wav.getnframes() <= dubbing.SR
    assert seen == [("Hẹn gặp lại!", {"style": "doc_truyen", "voice": "A"})]
    assert (folder / "state.json").read_bytes() == before
    assert not list(folder.parent.glob("*/render.json"))


def test_reviewed_tail_is_not_silently_cut_off_by_mux(tmp_path, monkeypatch):
    voice(monkeypatch, lambda text, kw: tone())
    cues = [Cue(0.96, 1, "End", "Tạm biệt.")]
    with pytest.raises(dubbing.DubError, match="dòng 1.*cuối video"):
        dubbing.build_dub_track(cues, 1, tmp_path, reviewed_units=dubbing.speech_units(cues))


@pytest.mark.parametrize("failure", ["empty", "silent", "dc", "click", "fragment", "exception"])
def test_bad_second_unit_retries_then_stops_without_partial_dub(tmp_path, monkeypatch, failure):
    cues = [Cue(0, 1, "Hi", "Chào.", "S1"), Cue(1, 2, "Bye", "Tạm biệt.", "S2")]
    units = dubbing.speech_units(cues)
    read = []

    def synth(text, kw):
        read.append(text)
        if text == units[0]["text"]:
            return tone()
        if failure == "exception":
            raise RuntimeError("engine unavailable")
        if failure == "dc":
            return np.full(dubbing.SR, .1)
        if failure in ("click", "fragment"):
            out = np.zeros(dubbing.SR)
            n = 2 if failure == "click" else dubbing.SR // 20
            out[100:100 + n] = np.cos(np.arange(n) * .03) * .2
            return out
        return np.zeros(0 if failure == "empty" else dubbing.SR)

    voice(monkeypatch, synth)
    with pytest.raises(dubbing.DubError, match="dòng 2"):
        dubbing.build_dub_track(cues, 2, tmp_path, reviewed_units=units)
    assert read.count(units[1]["text"]) == 1 + dubbing.RUNAWAY_RETRIES
    assert not (tmp_path / "dub.wav").exists()


@pytest.mark.parametrize("selected", ["A", dubbing.CLONE_VOICE])
def test_reopened_approval_renders_the_recording_heard_not_a_second_performance(scene, studio_client, monkeypatch, selected):
    _, data = scene
    reads, references = [], []

    def synth(text, kw):
        reads.append((text, dict(kw)))
        return .2 * np.sin(np.arange(dubbing.SR // 2) * (.02 * len(reads)))

    def ref(src, cues, out, speaker):
        references.append((speaker, cues[0].start))
        return (5, 2)

    voice(monkeypatch, synth)
    monkeypatch.setattr(dubbing, "clone_available", lambda: (True, ""))
    monkeypatch.setattr(dubbing, "compose_reference", ref)
    mix = {"voice": "A", "voices": {"S1": selected, "S2": "A"}, "style": "doc_truyen", "offset": .25, "max_speed": 1.5}
    draft = studio_client.post("/api/tts/script", json=data).json()
    row = draft["units"][0]

    def audition():
        r = studio_client.post("/api/projects/scene/dub-preview", json={**data, **mix, "voice": selected, "unit": row})
        assert r.is_success and float(r.headers["x-preview-start"]) == .25
        return r.content

    old = audition()
    row["text"] = "Chào cả nhà!"
    heard = audition()
    assert heard != old and audition() == heard
    assert len(reads) == 2
    assert references == ([("S1", 0), ("S1", 0)] if selected == dubbing.CLONE_VOICE else [])
    ok = studio_client.post("/api/projects/scene/dub-review", json={**data, "review": draft, "playback": mix})
    assert ok.is_success, ok.text
    reopened = studio_client.get("/api/projects/scene").json()["dub_review"]
    assert reopened["playback"] == mix
    cfg = {"outputs": {"dub": True}, "dub": {"approved_script": reopened["token"], "original_mode": "mute",
                                             "auto_level": False}, "learn": False}
    url = "/api/jobs/scene/render"
    for change in ({"style": "tin_tuc"}, {"voices": {"S1": "B"}}, {"max_speed": 2}):
        assert studio_client.post(url, json={**cfg, "dub": {**cfg["dub"], **change}}).status_code == 409
    assert studio_client.post(url, json={**cfg, "offset": 0}).status_code == 409
    monkeypatch.setattr(job_api, "run_in_thread", lambda job, target: target(job))
    monkeypatch.setattr(dubbing, "extract_references", lambda *a, **kw: pytest.fail("already heard this clone"))
    monkeypatch.setattr(dubbing, "mux_dub", lambda video, wav, dst, **kw: dst.touch())
    rendered = studio_client.post(url, json=cfg)
    assert rendered.is_success, rendered.text
    job = jobs.get_job(rendered.json()["job_id"])
    assert [t for t, _ in reads[2:]] == ["Tạm biệt."]
    assert reads[-1][1] == {"voice": "A", "style": "doc_truyen"}
    assert job.result["dub_stats"]["reused"] == 1
    with wave.open(io.BytesIO(heard)) as preview, wave.open(str(job.dir / "dub.wav")) as track:
        track.setpos(dubbing.SR // 4)
        assert preview.readframes(preview.getnframes()) == track.readframes(preview.getnframes())


def test_spill_into_next_line_is_reported_in_preview_approval_and_render(scene, studio_client, monkeypatch, workdir):
    _, data = scene
    data["cues"][1]["start"] = .25  # Overlapping subtitles are legal; overlapping reviewed performances aren't.
    voice(monkeypatch, lambda text, kw: tone())
    draft = studio_client.post("/api/tts/script", json=data).json()
    mix = {"voice": "A", "max_speed": 1}
    preview = studio_client.post("/api/projects/scene/dub-preview", json={**data, **mix, "unit": draft["units"][0]})
    assert preview.is_success
    assert float(preview.headers["x-preview-overrun"]) == pytest.approx(.25)
    approval = studio_client.post("/api/projects/scene/dub-review", json={**data, "review": draft, "playback": mix})
    assert approval.status_code == 422 and "#1" in approval.text
    cues = [Cue.from_dict(r) for r in data["cues"]]
    units = dub_review.approved(cues, draft, "scene", "en", "vi", False)
    with pytest.raises(dubbing.DubError, match="dòng 1.*dòng #2"):
        dubbing.build_dub_track(cues, 4, workdir, max_speed=1, reviewed_units=units)
    assert not (workdir / "dub.wav").exists()


def test_trying_another_take_does_not_replace_the_approved_one(scene, studio_client, monkeypatch):
    folder, data = scene
    calls = []

    def synth(text, kw):
        calls.append(text)
        return .25 * np.sin(np.arange(dubbing.SR // 2) * (.03 * len(calls)))

    voice(monkeypatch, synth)
    draft = studio_client.post("/api/tts/script", json=data).json()
    row = draft["units"][0]
    mix = {"voice": "A"}

    def listen(another=False):
        r = studio_client.post("/api/projects/scene/dub-preview", json={**data, **mix, "unit": row, "another": another})
        assert r.is_success, r.text if not r.is_success else ""
        return r

    original = listen()
    req = {**data, "review": draft, "playback": mix}
    approve = "/api/projects/scene/dub-review"
    first = studio_client.post(approve, json=req)
    assert first.is_success
    before = (folder / "state.json").read_bytes()
    other = listen(another=True)
    assert other.content != original.content and (folder / "state.json").read_bytes() == before
    assert listen().content == original.content
    row["variant"] = other.headers["x-preview-variant"]
    assert listen().content == other.content and len(calls) == 2
    req["previous"] = first.json()["token"]
    second = studio_client.post(approve, json=req)
    assert second.is_success and second.json()["token"] != req["previous"]
    assert projects.full("scene")["dub_review"]["units"][0]["variant"] == row["variant"]
    monkeypatch.setattr(job_api, "run_in_thread", lambda job, target: target(job))
    monkeypatch.setattr(dubbing, "mux_dub", lambda video, wav, dst, **kw: dst.touch())
    cfg = {"outputs": {"dub": True}, "dub": {"approved_script": second.json()["token"], "original_mode": "mute",
                                             "auto_level": False}, "learn": False}
    render = "/api/jobs/scene/render"
    rendered = studio_client.post(render, json=cfg)
    assert rendered.is_success, rendered.text
    with wave.open(io.BytesIO(other.content)) as take, wave.open(str(jobs.get_job(rendered.json()["job_id"]).dir / "dub.wav")) as track:
        assert take.readframes(take.getnframes()) == track.readframes(take.getnframes())
    (folder / ".auditions").rename(folder / "offline-auditions")
    denied = studio_client.post(render, json=cfg)
    assert denied.status_code == 409 and "#1" in denied.text
