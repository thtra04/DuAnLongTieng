"""Kiểm thử bảng nhân vật → giọng (HP-1 + HP-2 lưu trong DB, HP-7).

Store `characters`, phần nối vào `projects` (mở lại / xoá dự án) và API
`/api/projects/{id}/characters`.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from backend.db import Voice, get_db
from backend.main import app
from backend.store import characters, projects
from backend.store.characters import CharacterError


@pytest.fixture(autouse=True)
def _db(tmp_db):
    """Mỗi test một DB riêng."""


# ------------------------------------------------------------------ sync


def test_sync_tao_vai_sap_theo_giay_noi():
    out = characters.sync("job1", [{"id": "S2", "seconds": 5.0}, {"id": "S1", "seconds": 30.0}])
    assert [c["label"] for c in out] == ["S1", "S2"]
    assert out[0] == {"label": "S1", "name": "", "seconds": 30.0, "gender": "", "f0": 0.0, "voice": "", "style": "", "ref_path": ""}


def test_sync_giu_ten_giong_da_dat_va_bo_nhan_khong_con():
    characters.sync("job1", [{"id": "S1", "seconds": 1}, {"id": "S3", "seconds": 2}])
    characters.update("job1", "S1", name="Nam chính", voice="v1")

    out = characters.sync("job1", [{"id": "S1", "seconds": 9}])
    assert out == [
        {"label": "S1", "name": "Nam chính", "seconds": 9.0, "gender": "", "f0": 0.0, "voice": "v1", "style": "tu_nhien", "ref_path": ""}
    ]


def test_sync_bo_qua_nhan_khong_hop_le_va_job_rong():
    assert characters.sync("", [{"id": "S1"}]) == []
    out = characters.sync("job1", [{"id": "S1"}, {"id": "../x"}, {"id": ""}, {}, "rác", None])
    assert [c["label"] for c in out] == ["S1"]


def test_sync_khong_lan_sang_du_an_khac():
    characters.sync("job1", [{"id": "S1"}])
    characters.sync("job2", [{"id": "S1"}, {"id": "S2"}])
    assert len(characters.list_for("job1")) == 1
    assert len(characters.list_for("job2")) == 2


# ------------------------------------------------------------------ update


def test_update_tao_vai_moi_neu_chua_co_va_gon_ten():
    c = characters.update("job1", "S7", name="  Vai   phụ  ")
    assert c == {"label": "S7", "name": "Vai phụ", "seconds": 0.0, "gender": "", "f0": 0.0, "voice": "", "style": "", "ref_path": ""}


def test_update_cat_ten_qua_dai():
    assert len(characters.update("job1", "S1", name="x" * 200)["name"]) == characters.MAX_NAME


def test_update_giong_roi_doi_phong_cach():
    characters.update("job1", "S1", voice="v1")
    c = characters.update("job1", "S1", style="tin_tuc")
    assert (c["voice"], c["style"]) == ("v1", "tin_tuc")


def test_update_phong_cach_khi_chua_co_giong_thi_bo_qua():
    c = characters.update("job1", "S1", style="tin_tuc")
    assert (c["voice"], c["style"]) == ("", "")


def test_update_giong_rong_thi_go_giong_khong_de_dong_mo_coi():
    characters.update("job1", "S1", voice="v1")
    assert characters.update("job1", "S1", voice="")["voice"] == ""
    with get_db() as db:
        assert db.query(Voice).count() == 0


def test_update_chi_doi_ten_khong_dung_giong():
    characters.update("job1", "S1", voice="v1")
    c = characters.update("job1", "S1", name="Tên")
    assert c["voice"] == "v1" and c["name"] == "Tên"


@pytest.mark.parametrize("label", ["", "../x", "S" * 17, "S 1", None])
def test_update_nhan_sai_bi_tu_choi(label):
    with pytest.raises(CharacterError):
        characters.update("job1", label, name="x")


def test_update_thieu_job_bi_tu_choi():
    with pytest.raises(CharacterError):
        characters.update("", "S1", name="x")


# ------------------------------------------------------------------ record_voices


def test_record_voices_ghi_giong_thuc_dung():
    characters.sync("job1", [{"id": "S1", "seconds": 3}, {"id": "S2", "seconds": 2}])
    out = characters.record_voices(
        "job1", ["S1", "S2", "S3", "../x"],
        voice_map={"S2": "v_nu"}, ref_map={"S1": "/x/S1.wav"},
        default_voice="v_chung", style="doc_truyen", clone_id="__clone__",
    )
    by = {c["label"]: c for c in out}
    assert set(by) == {"S1", "S2", "S3"}
    assert (by["S1"]["voice"], by["S1"]["ref_path"]) == ("__clone__", "/x/S1.wav")
    assert (by["S2"]["voice"], by["S2"]["style"]) == ("v_nu", "doc_truyen")
    assert by["S3"]["voice"] == "v_chung", "vai có trong phụ đề mà DB chưa biết -> tạo mới"
    assert by["S1"]["seconds"] == 3.0, "không đụng số giây nói đã đo"


def test_record_voices_ghi_de_giong_cu():
    characters.update("job1", "S1", voice="v_cu")
    out = characters.record_voices("job1", ["S1"], {"S1": "v_moi"}, {}, "v", "tu_nhien")
    assert out[0]["voice"] == "v_moi"


def test_record_voices_job_rong_khong_ghi():
    assert characters.record_voices("", ["S1"], {}, {}, "v", "s") == []


# ------------------------------------------------------------------ delete_for


def test_delete_for_xoa_ca_giong_va_khong_dung_du_an_khac():
    characters.update("job1", "S1", voice="v1")
    characters.update("job1", "S2", voice="v1")
    characters.update("job2", "S1", voice="v1")

    assert characters.delete_for("job1") == 2
    assert characters.list_for("job1") == []
    assert len(characters.list_for("job2")) == 1
    with get_db() as db:
        assert db.query(Voice).count() == 1
    assert characters.delete_for("job1") == 0
    assert characters.delete_for("") == 0


# ------------------------------------------------------------------ nối với projects


@pytest.fixture
def kho(workdir, monkeypatch):
    jobs = workdir / "jobs"
    uploads = workdir / "uploads"
    jobs.mkdir()
    uploads.mkdir()
    from backend.api import deps, jobs as api_jobs, media as api_media

    for mod in (projects, deps, api_jobs, api_media):
        monkeypatch.setattr(mod, "JOB_DIR", jobs, raising=False)
        monkeypatch.setattr(mod, "UPLOAD_DIR", uploads, raising=False)
    return workdir


def tao_du_an(kho, job_id="job1"):
    folder = kho / "jobs" / job_id
    folder.mkdir(parents=True)
    state = {
        "video_path": "",
        "video_name": "phim.mp4",
        "info": {"duration": 10.0, "width": 0, "height": 0},
        "source_lang": "zh",
        "target_lang": "vi",
        "cues": [{"start": 0, "end": 1, "text": "a", "text2": "b", "speaker": "S1"}],
        "speakers": [{"id": "S1", "lines": 1, "seconds": 1.0}],
        "cfg": {},
    }
    (folder / "state.json").write_text(json.dumps(state), encoding="utf-8")


def test_full_kem_nhan_vat_tu_db(kho):
    tao_du_an(kho)
    characters.update("job1", "S1", name="Nam chính", voice="v1")
    item = projects.full("job1")
    assert item["characters"] == [
        {"label": "S1", "name": "Nam chính", "seconds": 0.0, "gender": "", "f0": 0.0, "voice": "v1", "style": "tu_nhien", "ref_path": ""}
    ]


def test_full_db_hong_van_mo_duoc_du_an(kho, monkeypatch):
    tao_du_an(kho)

    def no(*a, **k):
        raise RuntimeError("db chết")

    monkeypatch.setattr(characters, "list_for", no)
    item = projects.full("job1")
    assert item["cues"] and item["characters"] == []


def test_xoa_du_an_thi_xoa_nhan_vat(kho):
    tao_du_an(kho)
    characters.update("job1", "S1", name="x", voice="v1")
    assert projects.delete("job1")["ok"]
    assert characters.list_for("job1") == []


# ------------------------------------------------------------------ API


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def test_api_lay_bang_nhan_vat(kho, client):
    tao_du_an(kho)
    characters.update("job1", "S1", name="Nữ chính")
    r = client.get("/api/projects/job1/characters")
    assert r.status_code == 200
    assert r.json()["characters"][0]["name"] == "Nữ chính"


def test_api_du_an_khong_ton_tai_404(kho, client):
    assert client.get("/api/projects/khong-co/characters").status_code == 404
    assert client.patch("/api/projects/khong-co/characters/S1", json={"name": "x"}).status_code == 404


def test_api_doi_ten_va_chon_giong_roi_doc_lai(kho, client):
    tao_du_an(kho)
    r = client.patch(
        "/api/projects/job1/characters/S1", json={"name": "Nữ chính", "voice": "v2", "style": "tin_tuc"}
    )
    assert r.status_code == 200
    assert r.json()["character"] == {
        "label": "S1", "name": "Nữ chính", "seconds": 0.0, "gender": "", "f0": 0.0, "voice": "v2", "style": "tin_tuc", "ref_path": ""
    }
    assert client.get("/api/projects/job1").json()["characters"][0]["voice"] == "v2"


def test_api_nhan_sai_400(kho, client):
    tao_du_an(kho)
    r = client.patch("/api/projects/job1/characters/" + "S" * 17, json={"name": "x"})
    assert r.status_code == 400


def test_api_payload_rong_khong_doi_gi(kho, client):
    tao_du_an(kho)
    characters.update("job1", "S1", name="Giữ")
    r = client.patch("/api/projects/job1/characters/S1", json={})
    assert r.json()["character"]["name"] == "Giữ"


# ------------------------------------------------------------------ nối với pipeline


def _cues():
    from backend.core.subtitles import Cue

    return [Cue(0.0, 5.0, "a"), Cue(5.0, 6.0, "b")]


def _stats(labeled: int) -> dict:
    return {"total": 2, "labeled": labeled, "unsure": 0, "empty": 2 - labeled, "speakers": 0}


def test_buoc_phan_doan_luu_nhan_vat_vao_db(workdir, monkeypatch):
    from backend.core import jobs, pipeline

    (workdir / "audio.wav").write_bytes(b"")  # có sẵn -> không gọi ffmpeg tách tiếng
    monkeypatch.setattr(pipeline.diarize, "run", lambda *a, **k: [])

    def gan(cues, turns):
        cues[0].speaker, cues[1].speaker = "S1", "S2"
        return _stats(2)

    monkeypatch.setattr(pipeline.diarize, "assign", gan)
    job = jobs.create_job("analyze", [jobs.Step("diarize", "Nhận diện")])

    speakers = pipeline._run_diarize(job, {}, workdir / "v.mp4", workdir, _cues())

    assert [s["id"] for s in speakers] == ["S1", "S2"]
    assert [(c["label"], c["seconds"]) for c in characters.list_for(job.id)] == [("S1", 5.0), ("S2", 1.0)]
    assert job.step("diarize").status == "done"


def test_luu_nhan_vat_hong_khong_lam_sap_buoc_phan_doan(workdir, monkeypatch):
    from backend.core import jobs, pipeline

    (workdir / "audio.wav").write_bytes(b"")
    monkeypatch.setattr(pipeline.diarize, "run", lambda *a, **k: [])
    monkeypatch.setattr(pipeline.diarize, "assign", lambda cues, turns: _stats(0))

    def no(*a, **k):
        raise RuntimeError("db chết")

    monkeypatch.setattr(pipeline.characters, "sync", no)
    job = jobs.create_job("analyze", [jobs.Step("diarize", "Nhận diện")])

    pipeline._run_diarize(job, {}, workdir / "v.mp4", workdir, _cues())

    assert job.step("diarize").status == "done"
    assert any("Không lưu được" in ln for ln in job.logs)
