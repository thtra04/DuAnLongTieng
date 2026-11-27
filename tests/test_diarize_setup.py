import struct
import wave
from types import SimpleNamespace

import huggingface_hub
import pytest
from huggingface_hub import constants

from backend.core import diarize
from backend.core.subtitles import Cue


@pytest.fixture
def empty_setup(monkeypatch, workdir):
    monkeypatch.setattr(diarize, "MODEL_ID", diarize.COMMUNITY)
    monkeypatch.setattr(diarize, "_pipeline", None)
    for key in ("HF_TOKEN", "HUGGINGFACE_TOKEN", "HUGGING_FACE_HUB_TOKEN"):
        monkeypatch.delenv(key, raising=False)
    # The status endpoint only probes specs; don't require GPU extras on CI.
    find_spec = diarize.importlib.util.find_spec
    monkeypatch.setattr(diarize.importlib.util, "find_spec", lambda name, *a, **kw:
                        object() if name in ("torch", "torchaudio", "pyannote.audio") else find_spec(name, *a, **kw))
    monkeypatch.setattr(constants, "HF_HUB_CACHE", str(workdir))
    monkeypatch.setattr(constants, "HF_HUB_OFFLINE", False)
    return workdir


def test_partial_download_is_not_a_ready_pipeline(empty_setup, monkeypatch):
    repo = empty_setup / ("models--" + diarize.COMMUNITY.replace("/", "--"))
    (repo / "refs").mkdir(parents=True)
    revision = "a" * 40
    (repo / "refs/main").write_text(revision)
    folder = repo / "snapshots" / revision
    folder.mkdir(parents=True)
    (folder / "config.yaml").write_text("pipeline: {}")
    assert diarize.setup_status()["state"] == "needs_token"
    for _, name in diarize._assets()[1:]:
        (folder / name).parent.mkdir(exist_ok=True)
        (folder / name).write_bytes(b"x" * 2048)
    monkeypatch.setattr(huggingface_hub, "get_hf_file_metadata", lambda *a, **kw: pytest.fail("unexpected Hub call"))
    assert diarize.setup_status()["state"] == "cached" and diarize.check_access()[0]
    (folder / "embedding/pytorch_model.bin").write_text("version https://git-lfs.github.com/spec/v1")
    assert diarize.setup_status()["state"] == "needs_token"


def test_gated_component_denied_before_analysis_without_echoing_secret(empty_setup, studio_client, monkeypatch):
    monkeypatch.setattr(diarize, "_legacy_api", True)
    monkeypatch.setattr(diarize, "MODEL_ID", diarize.LEGACY)
    token, calls = "hf_simulated_read_only", []
    def metadata(url, **kwargs):
        assert kwargs["token"] == token and url.startswith("https://huggingface.co/")
        calls.append(url)
        if diarize.SEGMENTATION in url:
            raise RuntimeError(f"403 Forbidden (fixture: {token})")
    monkeypatch.setattr(huggingface_hub, "get_hf_file_metadata", metadata)
    request = {"hf_token": token}
    result = studio_client.post("/api/diarize/check", json=request)
    assert not result.json()["ok"] and diarize.SEGMENTATION in result.json()["message"]
    assert token not in result.text and len(calls) == 2
    result = studio_client.post("/api/analyze", json={**request, "diarize": True, "source_type": "url",
                                                      "url": "https://example.com/fixture"})
    assert result.status_code == 400 and token not in result.text and "job_id" not in result.json()


def test_token_is_not_a_substitute_for_dependencies(empty_setup, monkeypatch):
    monkeypatch.setenv("HF_TOKEN", "hf_only_a_fixture")
    monkeypatch.setattr(diarize.importlib.util, "find_spec", lambda name: None)
    status = diarize.setup_status()
    assert status["has_token"] and not status["available"] and status["state"] == "missing_dependency"
    assert "hf_only_a_fixture" not in str(status)


def test_offline_missing_assets_never_tries_a_token(empty_setup, monkeypatch):
    monkeypatch.setattr(constants, "HF_HUB_OFFLINE", True)
    monkeypatch.setattr(huggingface_hub, "get_hf_file_metadata", lambda *a, **k: pytest.fail("unexpected Hub call"))
    assert diarize.setup_status("hf_qa")["state"] == "offline"
    assert not diarize.check_access("hf_qa")[0]


def test_pipeline_gets_pcm_not_a_filename_and_reports_batch_progress(workdir, monkeypatch):
    pytest.importorskip("torch")
    wav = workdir / "sample.wav"
    with wave.open(str(wav), "wb") as out:
        out.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        out.writeframes(struct.pack("<4h", -32768, 0, 16384, 32767))
    def pipeline(audio, num_speakers, hook):
        assert num_speakers == 2 and audio["sample_rate"] == 16000
        assert audio["waveform"].tolist()[0] == pytest.approx([-1., 0., .5, 32767 / 32768])
        for stage in ("segmentation", "embeddings"):
            for n in (0, 1, 2):
                hook(stage, None, total=2, completed=n)
        turns = [(SimpleNamespace(start=1, end=2), 0, "B"), (SimpleNamespace(start=0, end=1), 0, "A")]
        return SimpleNamespace(exclusive_speaker_diarization=SimpleNamespace(itertracks=lambda **kw: iter(turns)))
    monkeypatch.setattr(diarize, "_load", lambda *a: pipeline)
    progress = []
    turns = diarize.run(wav, num_speakers=2, on_progress=progress.append)
    assert [t["speaker"] for t in turns] == ["S1", "S2"]
    assert progress == sorted(set(progress)) and progress[-1] == 1 and len(progress) >= 4


def test_tied_speech_is_flagged_and_fixed_roles_survive():
    cues = [Cue(0, 1, "a"), Cue(1, 2, "b", speaker="Guest", speaker_fixed=True)]
    turns = [{"start": 0, "end": 2, "speaker": s} for s in ("S1", "S2")]
    stats = diarize.assign(cues, turns)
    assert stats["review_at"] == [0] and stats["unsure"] == 1
    assert cues[1].speaker == "Guest"
    diarize.assign(cues, [])
    assert not cues[0].speaker and cues[1].speaker == "Guest"
