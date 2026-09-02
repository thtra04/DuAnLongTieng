"""Kiểm thử đọc lại dự án cũ từ đĩa và xoá dự án.

Danh sách job trong RAM mất khi khởi động lại tool, nhưng `state.json` vẫn nằm
đó — module này là thứ cho phép mở lại việc cũ mà không phải nghe & dịch lại.
"""

from __future__ import annotations

import json

import pytest

from app import films, projects


@pytest.fixture(autouse=True)
def kho_tam(workdir, monkeypatch):
    """Thư mục job / upload / kho phim riêng cho mỗi test."""
    jobs = workdir / "jobs"
    uploads = workdir / "uploads"
    jobs.mkdir()
    uploads.mkdir()
    monkeypatch.setattr(projects, "JOB_DIR", jobs)
    monkeypatch.setattr(projects, "UPLOAD_DIR", uploads)
    monkeypatch.setattr(films, "STORE", workdir / "films.json")
    return workdir


def tao_job(kho_tam, job_id="job1", *, video=True, cues=2, url="", part=None, ten="phim.mp4"):
    """Dựng một thư mục job giống hệt cái pipeline ghi ra."""
    folder = kho_tam / "jobs" / job_id
    (folder / "source").mkdir(parents=True)

    video_path = ""
    if video:
        p = folder / "source" / ten
        p.write_bytes(b"gia-lam-video" * 100)
        video_path = str(p)

    state = {
        "video_path": video_path,
        "video_name": ten,
        "info": {"duration": 120.0, "width": 1920, "height": 1080},
        "source_lang": "zh",
        "target_lang": "vi",
        "cues": [
            {"start": i, "end": i + 1, "text": f"câu {i}", "text2": f"dịch {i}", "speaker": ""}
            for i in range(cues)
        ],
        "cfg": {"url": url, "part": part},
    }
    (folder / "state.json").write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    return folder


# ------------------------------------------------------------ đọc lại


def test_doc_lai_thong_tin_du_an(kho_tam):
    tao_job(kho_tam)
    item = projects.summary("job1")

    assert item["id"] == "job1"
    assert item["video_name"] == "phim.mp4"
    assert item["duration"] == 120.0
    assert item["cue_count"] == 2
    assert item["source_lang"] == "zh" and item["target_lang"] == "vi"
    assert item["video_ok"] is True


def test_du_an_mat_video_goc_van_doc_duoc(kho_tam):
    tao_job(kho_tam, video=False)
    item = projects.summary("job1")
    assert item is not None
    assert item["video_ok"] is False, "phải báo rõ để giao diện khoá nút nung/lồng tiếng"


def test_thu_muc_khong_co_state_thi_bo_qua(kho_tam):
    (kho_tam / "jobs" / "rac").mkdir()
    assert projects.summary("rac") is None


def test_state_hong_khong_lam_no_chuong_trinh(kho_tam):
    folder = kho_tam / "jobs" / "hong"
    folder.mkdir()
    (folder / "state.json").write_text("{ hỏng", encoding="utf-8")
    assert projects.summary("hong") is None


def test_state_dung_json_nhung_sai_kieu(kho_tam):
    folder = kho_tam / "jobs" / "la"
    folder.mkdir()
    (folder / "state.json").write_text("[1, 2, 3]", encoding="utf-8")
    assert projects.summary("la") is None


def test_full_kem_toan_bo_phu_de(kho_tam):
    tao_job(kho_tam, cues=5)
    item = projects.full("job1")
    assert len(item["cues"]) == 5
    assert item["cues"][0]["text"] == "câu 0"


def test_full_kem_danh_sach_nhan_vat(kho_tam):
    folder = tao_job(kho_tam)
    state = json.loads((folder / "state.json").read_text(encoding="utf-8"))
    state["speakers"] = [{"id": "S1", "lines": 2, "seconds": 2.0}]
    (folder / "state.json").write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")

    assert projects.full("job1")["speakers"][0]["id"] == "S1"


def test_du_an_khong_co_thi_tra_none(kho_tam):
    assert projects.full("khong-co") is None


# ------------------------------------------------------- danh sách


def test_liet_ke_moi_nhat_truoc(kho_tam):
    import os
    import time

    tao_job(kho_tam, "cu")
    time.sleep(0.02)
    tao_job(kho_tam, "moi")
    os.utime(kho_tam / "jobs" / "moi" / "state.json", (time.time() + 10, time.time() + 10))

    assert [it["id"] for it in projects.list_all()][0] == "moi"


def test_gioi_han_so_luong(kho_tam):
    for i in range(5):
        tao_job(kho_tam, f"job{i}")
    assert len(projects.list_all(limit=3)) == 3


def test_thu_muc_job_chua_ton_tai(kho_tam, monkeypatch):
    monkeypatch.setattr(projects, "JOB_DIR", kho_tam / "khong-co")
    assert projects.list_all() == []


# ------------------------------------------------------- file xuất


def test_liet_ke_file_da_xuat(kho_tam):
    folder = tao_job(kho_tam)
    (folder / "phim.vi.srt").write_text("1\n", encoding="utf-8")
    (folder / "phim.hardsub.mp4").write_bytes(b"x" * 50)

    ten = {f["name"] for f in projects.summary("job1")["files"]}
    assert ten == {"phim.vi.srt", "phim.hardsub.mp4"}


def test_bo_qua_file_lam_viec_noi_bo(kho_tam):
    folder = tao_job(kho_tam)
    for name in ("burn.ass", "audio.wav", "dub.wav", "_soft.srt", "voice_ref.wav"):
        (folder / name).write_bytes(b"x")

    assert projects.summary("job1")["files"] == []


def test_gom_ca_file_o_thu_muc_job_render(kho_tam):
    """run_render ghi kết quả vào thư mục job render, không cùng chỗ state.json."""
    tao_job(kho_tam)
    render = kho_tam / "jobs" / "render1"
    render.mkdir()
    (render / "render.json").write_text('{"source_job": "job1"}', encoding="utf-8")
    (render / "phim.vi.srt").write_text("1\n", encoding="utf-8")

    assert [f["name"] for f in projects.summary("job1")["files"]] == ["phim.vi.srt"]


def test_lay_file_de_tai_ve(kho_tam):
    folder = tao_job(kho_tam)
    (folder / "phim.vi.srt").write_text("1\n", encoding="utf-8")
    assert projects.output_file("job1", "phim.vi.srt").name == "phim.vi.srt"


def test_khong_lay_duoc_file_ngoai_thu_muc(kho_tam):
    """Chỉ nhận tên file trần — không cho đi ngược thư mục."""
    tao_job(kho_tam)
    assert projects.output_file("job1", "../../pyproject.toml") is None
    assert projects.output_file("job1", "khong-co.srt") is None


# ------------------------------------------------------------- video


def test_tim_lai_video_goc(kho_tam):
    tao_job(kho_tam)
    assert projects.video_path("job1").name == "phim.mp4"


def test_video_bi_doi_cho_van_tim_trong_thu_muc_job(kho_tam):
    folder = tao_job(kho_tam)
    state = json.loads((folder / "state.json").read_text(encoding="utf-8"))
    state["video_path"] = "D:/da/bi/xoa/phim.mp4"
    (folder / "state.json").write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")

    assert projects.video_path("job1").name == "phim.mp4"


def test_video_that_su_mat_thi_tra_none(kho_tam):
    tao_job(kho_tam, video=False)
    assert projects.video_path("job1") is None


# --------------------------------------------------------------- xoá


def test_xoa_du_an(kho_tam):
    tao_job(kho_tam)
    ket_qua = projects.delete("job1")

    assert ket_qua["ok"] is True
    assert ket_qua["freed"] > 0
    assert not (kho_tam / "jobs" / "job1").exists()


def test_xoa_ca_thu_muc_render_di_kem(kho_tam):
    tao_job(kho_tam)
    render = kho_tam / "jobs" / "render1"
    render.mkdir()
    (render / "render.json").write_text('{"source_job": "job1"}', encoding="utf-8")

    projects.delete("job1")
    assert not render.exists()


def test_xoa_du_an_khong_ton_tai(kho_tam):
    assert projects.delete("khong-co")["ok"] is False


def test_xoa_job_thi_tap_quay_ve_chua_co_video(kho_tam):
    tao_job(kho_tam)
    film = films.create("Bộ")
    films.add_episode(film["id"], no=1)
    films.bind(film["id"], 1, "job1")

    projects.delete("job1")
    assert films.all_films()[0]["episodes"][0]["job"] is None


def test_khong_xoa_video_upload_con_du_an_khac_dung(kho_tam):
    """Video upload dùng chung giữa nhiều dự án — xoá một cái không được đụng."""
    media = kho_tam / "uploads" / "media1"
    media.mkdir()
    video = media / "chung.mp4"
    video.write_bytes(b"x" * 100)

    for job_id in ("jobA", "jobB"):
        folder = kho_tam / "jobs" / job_id
        folder.mkdir()
        (folder / "state.json").write_text(
            json.dumps({"video_path": str(video), "video_name": "chung.mp4",
                        "info": {}, "cues": [], "cfg": {}}),
            encoding="utf-8",
        )

    ket_qua = projects.delete("jobA", with_source=True)
    assert ket_qua["source_deleted"] is False
    assert video.exists(), "còn jobB đang dùng, không được xoá"


def test_xoa_video_upload_khi_khong_con_ai_dung(kho_tam):
    media = kho_tam / "uploads" / "media1"
    media.mkdir()
    video = media / "rieng.mp4"
    video.write_bytes(b"x" * 100)

    folder = kho_tam / "jobs" / "jobA"
    folder.mkdir()
    (folder / "state.json").write_text(
        json.dumps({"video_path": str(video), "video_name": "rieng.mp4",
                    "info": {}, "cues": [], "cfg": {}}),
        encoding="utf-8",
    )

    assert projects.delete("jobA", with_source=True)["source_deleted"] is True
    assert not video.exists()


# ------------------------------------------------------- dashboard


def test_dashboard_gom_tap_vao_bo(kho_tam):
    tao_job(kho_tam, "job1")
    film = films.create("Bộ")
    films.add_episode(film["id"], no=1)
    films.add_episode(film["id"], no=2)
    films.bind(film["id"], 1, "job1")

    data = projects.dashboard()
    bo = data["films"][0]
    assert bo["total"] == 2 and bo["done"] == 1
    assert data["loose"] == []


def test_dashboard_job_chua_thuoc_bo_nao(kho_tam):
    tao_job(kho_tam, "le")
    data = projects.dashboard()
    assert [it["id"] for it in data["loose"]] == ["le"]


def test_dashboard_tap_tro_toi_job_da_bi_xoa(kho_tam):
    film = films.create("Bộ")
    films.add_episode(film["id"], no=1)
    films.bind(film["id"], 1, "job-da-xoa")

    tap = projects.dashboard()["films"][0]["episodes"][0]
    assert tap["stale"] is True and tap["job"] is None
