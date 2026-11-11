"""Kiểm thử các endpoint còn lại, và thử khai thác đường dẫn."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from backend.store import films, projects
from backend import main
from backend.main import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def kho_tam(workdir, monkeypatch, tmp_db):
    jobs = workdir / "jobs"
    uploads = workdir / "uploads"
    jobs.mkdir()
    uploads.mkdir()
    from backend.api import deps, jobs as api_jobs, media as api_media

    for mod in (projects, deps, api_jobs, api_media):
        monkeypatch.setattr(mod, "JOB_DIR", jobs, raising=False)
        monkeypatch.setattr(mod, "UPLOAD_DIR", uploads, raising=False)
    return workdir


# ------------------------------------------------------------- trang


def test_trang_chu_tra_html(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "VSub" in r.text


def test_trang_chu_gan_dau_thoi_gian_de_pha_cache(client):
    """Sửa code mà trình duyệt vẫn chạy bản cũ là lỗi rất khó lần ra."""
    r = client.get("/")
    assert "/js/core.js?v=" in r.text
    assert "/css/style.css?v=" in r.text


def test_trang_chu_khong_cho_cache(client):
    assert client.get("/").headers.get("cache-control") == "no-cache"


def test_phuc_vu_js_va_css(client):
    js = client.get("/js/core.js")
    css = client.get("/css/style.css")
    assert js.status_code == 200 and "javascript" in js.headers["content-type"]
    assert css.status_code == 200 and "css" in css.headers["content-type"]


# --------------------------------------------------- thử khai thác đường dẫn


@pytest.mark.parametrize(
    "doc",
    [
        "../../../../pyproject.toml",
        "..%2F..%2Fpyproject.toml",
        "....//....//pyproject.toml",
        "..\\..\\pyproject.toml",
    ],
)
def test_khong_doc_duoc_file_ngoai_thu_muc_qua_media_id(client, doc):
    r = client.get(f"/api/media/{doc}/stream")
    assert r.status_code in (307, 404), f"media_id {doc!r} không được lọt"
    if r.status_code == 200:
        assert "[project]" not in r.text


@pytest.mark.parametrize("doc", ["../../..", "..", "../uploads"])
def test_khong_doc_duoc_thu_muc_ngoai_qua_analyze(client, doc):
    """`media_id` ở đây đến từ thân JSON nên không bị router chặn giúp."""
    r = client.post("/api/analyze", json={"source_type": "file", "media_id": doc})
    assert r.status_code == 400
    assert "media_id" in r.json()["error"] or "video" in r.json()["error"].lower()


@pytest.mark.parametrize("doc", ["../../pyproject.toml", "..%2Fstate.json"])
def test_khong_tai_duoc_file_ngoai_qua_project(client, doc):
    r = client.get(f"/api/projects/job1/files/{doc}")
    assert r.status_code in (307, 404)


# --------------------------------------------------------- kiểm tra link


def test_link_rong_bi_tu_choi(client):
    r = client.post("/api/link/inspect", json={"url": ""})
    assert r.status_code == 400 and "Thiếu link" in r.json()["error"]


@pytest.mark.parametrize("url", ["file:///C:/Windows/win.ini", "ftp://x/y", "javascript:alert(1)", "x.com"])
def test_chi_chap_nhan_http(client, url):
    r = client.post("/api/link/inspect", json={"url": url})
    assert r.status_code == 400
    assert "http" in r.json()["error"].lower()


# ------------------------------------------------------------- upload


def test_tu_choi_dinh_dang_khong_ho_tro(client):
    r = client.post("/api/upload", files={"file": ("virus.exe", b"MZ", "application/x-msdownload")})
    assert r.status_code == 400 and ".exe" in r.json()["error"]


def test_tu_choi_file_rac_du_duoi_hop_le(client):
    """`probe` trả về số 0 thay vì ném lỗi, nên phải tự kiểm chứ đừng tin nó."""
    r = client.post("/api/upload", files={"file": ("gia.mp4", b"day khong phai video", "video/mp4")})
    assert r.status_code == 400
    assert "không phải video" in r.json()["error"]


# ------------------------------------------------------ cache bản dịch


def test_xem_thong_tin_cache(client):
    data = client.get("/api/translation-cache").json()
    assert set(data) == {"entries", "bytes"}
    assert isinstance(data["entries"], int)


# ------------------------------------------------------------ bộ phim


def test_tao_bo_phim(client, kho_tam):
    r = client.post("/api/films", json={"name": "Bộ mới"})
    assert r.status_code == 200
    assert r.json()["film"]["name"] == "Bộ mới"


def test_tao_bo_khong_ten_bi_tu_choi(client, kho_tam):
    assert client.post("/api/films", json={"name": "  "}).status_code == 400


def test_doi_ten_bo(client, kho_tam):
    film = client.post("/api/films", json={"name": "Cũ"}).json()["film"]
    r = client.patch(f"/api/films/{film['id']}", json={"name": "Mới"})
    assert r.json()["film"]["name"] == "Mới"


def test_doi_ten_bo_khong_ton_tai(client, kho_tam):
    assert client.patch("/api/films/khong-co", json={"name": "X"}).status_code == 400


def test_them_va_xoa_tap(client, kho_tam):
    film = client.post("/api/films", json={"name": "Bộ"}).json()["film"]
    tap = client.post(f"/api/films/{film['id']}/episodes", json={}).json()["episode"]
    assert tap["no"] == 1
    assert client.delete(f"/api/films/{film['id']}/episodes/1").status_code == 200


def test_so_tap_sai_kieu_bi_tu_choi(client, kho_tam):
    film = client.post("/api/films", json={"name": "Bộ"}).json()["film"]
    r = client.post(f"/api/films/{film['id']}/episodes", json={"no": "tập ba"})
    assert r.status_code == 400


def test_xoa_tap_khong_ton_tai(client, kho_tam):
    film = client.post("/api/films", json={"name": "Bộ"}).json()["film"]
    assert client.delete(f"/api/films/{film['id']}/episodes/99").status_code == 404


def test_gan_job_khong_ton_tai_vao_tap(client, kho_tam):
    film = client.post("/api/films", json={"name": "Bộ"}).json()["film"]
    client.post(f"/api/films/{film['id']}/episodes", json={})
    r = client.post(f"/api/films/{film['id']}/episodes/1/bind", json={"job": "khong-co"})
    assert r.status_code == 404


def test_gan_thieu_id_job(client, kho_tam):
    film = client.post("/api/films", json={"name": "Bộ"}).json()["film"]
    client.post(f"/api/films/{film['id']}/episodes", json={})
    assert client.post(f"/api/films/{film['id']}/episodes/1/bind", json={}).status_code == 400


def test_xoa_bo_khong_ton_tai(client, kho_tam):
    assert client.delete("/api/films/khong-co").status_code == 404


def test_danh_sach_bo_phim(client, kho_tam):
    data = client.get("/api/films").json()
    assert set(data) >= {"films", "loose", "total_size"}


# ---------------------------------------------------------------- job


def test_huy_job_khong_ton_tai(client):
    assert client.post("/api/jobs/khong-co/cancel").status_code == 404


def test_huy_job_dang_chay(client):
    from backend.core.jobs import create_job

    job = create_job("analyze", [])
    r = client.post(f"/api/jobs/{job.id}/cancel")
    assert r.status_code == 200 and job.cancel.is_set()


def test_trang_thai_job(client):
    from backend.core.jobs import create_job

    job = create_job("analyze", [])
    data = client.get(f"/api/jobs/{job.id}").json()
    assert data["id"] == job.id and data["status"] == "queued"


# -------------------------------------------------------------- render


def test_render_khi_phien_da_het_han(client):
    r = client.post("/api/jobs/khong-co/render", json={"outputs": {"srt": True}})
    assert r.status_code == 410
    assert "hết hạn" in r.json()["error"]


def test_render_khong_chon_dinh_dang_nao(client, kho_tam):
    folder = kho_tam / "jobs" / "job1"
    folder.mkdir(parents=True)
    (folder / "state.json").write_text(
        json.dumps({
            "video_path": "", "video_name": "x.mp4", "info": {},
            "cues": [{"start": 0, "end": 1, "text": "a", "text2": "b"}], "cfg": {},
        }),
        encoding="utf-8",
    )
    r = client.post("/api/jobs/job1/render", json={"outputs": {}, "cues": [{"start": 0, "end": 1, "text": "a"}]})
    assert r.status_code == 400


# ------------------------------------------------------------ bộ nhớ dịch


def test_xuat_voi_ban_dich_da_sua_thi_ghi_vao_bo_nho_dich(client, kho_tam, monkeypatch):
    from backend.api import jobs as api_jobs
    from backend.store import memory

    monkeypatch.setattr(memory, "_ready", False)
    folder = kho_tam / "jobs" / "job9"
    folder.mkdir(parents=True)
    (folder / "state.json").write_text(
        json.dumps({
            "video_path": "", "video_name": "x.mp4", "info": {}, "cfg": {},
            "source_lang": "zh", "target_lang": "vi",
            "cues": [{"start": 0, "end": 1, "text": "郎君。", "text2": "Lang Jun."},
                     {"start": 2, "end": 3, "text": "走吧。", "text2": "Đi thôi."}],
        }, ensure_ascii=False),
        encoding="utf-8",
    )
    sua = [{"start": 0, "end": 1, "text": "郎君。", "text2": "Lang quân."},
           {"start": 2, "end": 3, "text": "走吧。", "text2": "Đi thôi."}]

    # yêu cầu bị từ chối (không chọn định dạng) thì không học
    assert client.post("/api/jobs/job9/render", json={"outputs": {}, "cues": sua}).status_code == 400
    assert memory.stats()["pairs"] == 0

    (folder / "state.json").write_text(
        json.dumps({
            "video_path": "", "video_name": "x.mp4", "info": {}, "cfg": {},
            "source_lang": "zh", "target_lang": "vi",
            "cues": [{"start": 0, "end": 1, "text": "郎君。", "text2": "Lang Jun."},
                     {"start": 2, "end": 3, "text": "走吧。", "text2": "Đi thôi."}],
        }, ensure_ascii=False),
        encoding="utf-8",
    )
    logs: list[str] = []

    class JobGia:
        id = "render1"
        dir = folder
        result: dict = {}

        def log(self, msg):
            logs.append(msg)

    monkeypatch.setattr(api_jobs, "create_job", lambda *a, **k: JobGia())
    monkeypatch.setattr(api_jobs, "run_in_thread", lambda *a, **k: None)
    r = client.post("/api/jobs/job9/render", json={"outputs": {"srt": True}, "cues": sua})
    assert r.status_code == 200
    assert memory.stats()["pairs"] == 1, "chỉ câu bị sửa mới được ghi nhớ"
    assert any("ghi nhớ 1 câu" in ln for ln in logs)
    assert client.get("/api/translation-memory").json()["pairs"] == 1
    assert client.delete("/api/translation-memory").json() == {"deleted": 1}
