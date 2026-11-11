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


# ------------------------------------------------- dòng thời gian (bước 4)


def _wav(path, seconds, amp, sr=8000):
    import math
    import struct
    import wave

    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(b"".join(
            struct.pack("<h", int(amp(i / sr) * 32000 * math.sin(i * 0.3))) for i in range(int(seconds * sr))))


def _du_an(kho_tam, name="jobw"):
    folder = kho_tam / "jobs" / name
    folder.mkdir(parents=True)
    (folder / "state.json").write_text(json.dumps({
        "video_path": "", "video_name": "x.mp4", "info": {"duration": 4}, "cfg": {},
        "cues": [{"start": 0, "end": 1, "text": "a", "text2": "b"}],
    }), encoding="utf-8")
    return folder


def test_song_am_tra_dinh_theo_dung_cho_co_tieng(client, kho_tam):
    folder = _du_an(kho_tam)
    _wav(folder / "audio.wav", 4, lambda t: 1.0 if 1 <= t < 2 else 0.0)
    r = client.get("/api/projects/jobw/waveform?points=400")
    assert r.status_code == 200
    data = r.json()
    assert data["duration"] == 4.0
    assert [t["id"] for t in data["tracks"]] == ["audio"]
    peaks = data["tracks"][0]["peaks"]
    assert len(peaks) == 400
    assert max(peaks[:95]) == 0 and max(peaks[205:]) == 0, "chỗ im phải phẳng"
    assert min(peaks[105:195]) > 0.5 and max(peaks) == 1.0, "chỗ có tiếng phải cao, chuẩn hoá về 1"
    assert (folder / "audio.peaks.json").is_file(), "phải lưu cache để mở lại không đọc lại cả file"
    assert client.get("/api/projects/jobw/waveform?points=400").json() == data


def test_song_am_uu_tien_giong_goc_va_nhac_nen_khi_da_tach(client, kho_tam):
    folder = _du_an(kho_tam, "jobs2")
    _wav(folder / "audio.wav", 2, lambda t: 1.0)
    # hai file tách nằm ở thư mục của một lần xuất trước
    render = kho_tam / "jobs" / "render7"
    render.mkdir()
    (render / "render.json").write_text(json.dumps({"source_job": "jobs2"}), encoding="utf-8")
    _wav(render / "vocals.wav", 2, lambda t: 1.0)
    _wav(render / "no_vocals.wav", 2, lambda t: 0.3)
    data = client.get("/api/projects/jobs2/waveform").json()
    assert [t["id"] for t in data["tracks"]] == ["vocals", "music"]


def test_song_am_khong_co_file_thi_rong_va_du_an_la_thi_404(client, kho_tam):
    _du_an(kho_tam, "jobs3")
    assert client.get("/api/projects/jobs3/waveform").json() == {"duration": 0.0, "tracks": []}
    assert client.get("/api/projects/khong-co/waveform").status_code == 404


def test_du_doan_thoi_luong_doc_bao_cau_tran_khung(client):
    cues = [
        {"start": 0, "end": 1.0, "text": "a", "speaker": "S1",
         "text2": "Đây là một câu rất dài mà không ai có thể đọc kịp trong vòng một giây đồng hồ cả."},
        {"start": 1.02, "end": 6.0, "text": "b", "text2": "Ừ.", "speaker": "S2"},
        {"start": 7, "end": 8, "text": "chưa dịch", "text2": ""},
    ]
    r = client.post("/api/reading-budget", json={"cues": cues})
    assert r.status_code == 200
    data = r.json()
    assert [it["cues"] for it in data["items"]] == [[0], [1]], "dòng chưa dịch không có gì để đọc"
    dai, ngan = data["items"]
    assert dai["over"] > 1 and dai["predicted"] > dai["budget"] and dai["start"] == 0
    assert ngan["over"] == 0
    assert data["tolerance"] > 0
    assert client.post("/api/reading-budget", json={"cues": "sai"}).status_code == 400


# ---------------------------------------------------------------- dịch lại


def test_dich_lai_giu_loi_goc_moc_gio_va_vai_chi_viet_lai_ban_dich(client, kho_tam, monkeypatch):
    import time as _time

    from backend.core import translate
    from backend.store import memory

    monkeypatch.setattr(memory, "_ready", False)
    monkeypatch.setattr(translate, "_CACHE_FILE", kho_tam / "cache.json")
    seen = {}

    def gia(texts, source, target, engine, on_progress=None, on_log=None):
        seen["texts"] = list(texts)
        return [f"moi:{t}" for t in texts]

    monkeypatch.setattr(translate, "_translate_deep", gia)
    folder = kho_tam / "jobs" / "jobr"
    folder.mkdir(parents=True)
    (folder / "state.json").write_text(json.dumps({
        "video_path": "", "video_name": "x.mp4", "info": {}, "cfg": {"engine": "google"},
        "source_lang": "zh", "target_lang": "vi",
        "cues": [{"start": 0, "end": 1, "text": "郎君。", "text2": "Lang Jun.", "speaker": "S1"},
                 {"start": 2, "end": 3, "text": "走吧。", "text2": "Đi thôi.", "speaker": "S2"}],
    }, ensure_ascii=False), encoding="utf-8")

    r = client.post("/api/jobs/jobr/retranslate", json={
        "engine": "google", "glossary": "郎君 = lang quân", "api_key": "bi-mat",
        "cues": [{"start": 0, "end": 1.5, "text": "郎君。", "text2": "", "speaker": "S1"},
                 {"start": 2, "end": 3, "text": "走吧。", "text2": "", "speaker": "S2"}],
    })
    assert r.status_code == 200
    job_id = r.json()["job_id"]
    for _ in range(100):
        j = client.get(f"/api/jobs/{job_id}").json()
        if j["status"] in ("done", "error"):
            break
        _time.sleep(0.05)
    assert j["status"] == "done", j.get("error")
    cues = j["result"]["cues"]
    assert "lang quân" in seen["texts"][0], "bộ thuật ngữ mới phải được áp"
    assert [c["text"] for c in cues] == ["郎君。", "走吧。"]
    assert [c["speaker"] for c in cues] == ["S1", "S2"] and cues[0]["end"] == 1.5
    assert cues[1]["text2"] == "moi:走吧。"
    saved = json.loads((folder / "state.json").read_text(encoding="utf-8"))
    assert saved["cues"][1]["text2"] == "moi:走吧。", "mở lại dự án phải thấy bản dịch mới"
    assert "bi-mat" not in json.dumps(saved), "API key không được ghi xuống đĩa"

    assert client.post("/api/jobs/khong-co/retranslate", json={"engine": "google"}).status_code == 410


# ---------------------------------------------------------------- dịch gọn câu dài
def test_dich_gon_chi_dong_dong_dang_dai_va_khong_ghi_gi_xuong_dia(client, monkeypatch):
    from backend.core import translate

    cues = [
        {"start": 80.65, "end": 83.21, "text": "郎君不是说把我吃穿不愁",
         "text2": "Lang quân chẳng phải đã nói sẽ cho thiếp ăn sung mặc sướng sao"},
        {"start": 84, "end": 87, "text": "你到底是谁", "text2": "Ngươi là ai"},
    ]
    seen = {}

    def fake_chat(engine, system, user, api_key, model, base_url, on_log=None):
        seen["system"], seen["user"] = system, user
        return "1|Lang quân chẳng bảo cho thiếp ăn sung mặc sướng sao"

    monkeypatch.setattr(translate, "_chat", fake_chat)
    r = client.post("/api/fit-lines", json={"cues": cues, "indices": [], "engine": "openai", "api_key": "k",
                                            "source_lang": "zh", "target_lang": "vi"})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["asked"] == 1 and data["method"] == "ai", "dòng 2 không dài thì không gửi đi"
    assert data["changes"] == [{"i": 0, "text2": "Lang quân chẳng bảo cho thiếp ăn sung mặc sướng sao",
                                "target": data["changes"][0]["target"], "fits": data["changes"][0]["fits"]}]
    # model nhận cả câu gốc lẫn bản dịch cũ, kèm giới hạn âm tiết nhỏ hơn số âm tiết hiện có (14)
    so, gioi_han, goc, cu = seen["user"].split("|")
    assert so == "1" and 1 <= int(gioi_han) < 14 and goc == cues[0]["text"] and cu == cues[0]["text2"]
    assert "DỊCH LẠI" in seen["system"]


def test_dich_gon_bo_qua_ban_khong_ngan_hon_va_engine_thuong_dung_luat(client, monkeypatch):
    from backend.core import translate

    dai = {"start": 0, "end": 1.0, "text": "好", "text2": "Thật ra thì tôi nghĩ là chuyện này rất là tốt đấy"}
    monkeypatch.setattr(translate, "_chat", lambda *a, **k: "1|" + dai["text2"] + " nhé bạn ơi")
    r = client.post("/api/fit-lines", json={"cues": [dai], "indices": [0], "engine": "openai", "api_key": "k"})
    assert r.json()["changes"] == [], "bản mới dài hơn thì không nhận"

    r = client.post("/api/fit-lines", json={"cues": [dai], "indices": [0], "engine": "google", "target_lang": "vi"})
    data = r.json()
    assert data["method"] == "rules" and data["asked"] == 1
    if data["changes"]:
        assert len(data["changes"][0]["text2"]) < len(dai["text2"])
    assert client.post("/api/fit-lines", json={"cues": "sai"}).status_code == 400
    assert client.post("/api/fit-lines", json={"cues": [dai], "indices": ["0"]}).status_code == 400


def test_dich_lai_du_an_chua_co_vai_thi_nhan_vai_va_luu_theo_du_an(client, kho_tam, monkeypatch):
    """Dự án cũ không dòng nào có vai: lượt dịch lại tách giọng nam / nữ, bảng vai lưu theo id dự án."""
    import time as _time

    from backend.core import pipeline, translate
    from backend.store import memory

    monkeypatch.setattr(memory, "_ready", False)
    monkeypatch.setattr(translate, "_CACHE_FILE", kho_tam / "cache.json")
    monkeypatch.setattr(translate, "_translate_deep", lambda texts, *a, **k: [f"moi:{t}" for t in texts])
    goi = {}

    def gia_tach(job, cfg, video_path, workdir, cues, speakers, clean_wav=None, project_id=None):
        goi["project_id"], goi["workdir"] = project_id, workdir.name
        job.start_step("gender")
        cues[0].speaker, cues[1].speaker = "S1", "S2"
        job.finish_step("gender")
        return [{"id": "S1", "gender": "M", "name": "Nam 1"}, {"id": "S2", "gender": "F", "name": "Nữ 1"}]

    monkeypatch.setattr(pipeline, "_run_gender", gia_tach)
    folder = kho_tam / "jobs" / "jobcu"
    folder.mkdir(parents=True)
    state = {"video_path": "", "video_name": "x.mp4", "info": {}, "cfg": {}, "source_lang": "zh",
             "target_lang": "vi", "speakers": [],
             "cues": [{"start": 0, "end": 1, "text": "郎君。", "text2": "", "speaker": ""},
                      {"start": 2, "end": 3, "text": "走吧。", "text2": "", "speaker": ""}]}
    (folder / "state.json").write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")

    def chay(payload):
        job_id = client.post("/api/jobs/jobcu/retranslate", json=payload).json()["job_id"]
        for _ in range(100):
            j = client.get(f"/api/jobs/{job_id}").json()
            if j["status"] in ("done", "error"):
                break
            _time.sleep(0.05)
        assert j["status"] == "done", j.get("error")
        return j

    j = chay({"engine": "google", "gender_split": False})
    assert not goi and [c["speaker"] for c in j["result"]["cues"]] == ["", ""], "tắt tách giọng thì không đụng tới vai"

    j = chay({"engine": "google", "gender_split": True})
    assert goi == {"project_id": "jobcu", "workdir": "jobcu"}
    assert [c["speaker"] for c in j["result"]["cues"]] == ["S1", "S2"]
    assert [s["name"] for s in j["result"]["speakers"]] == ["Nam 1", "Nữ 1"]
    assert [s["key"] for s in j["steps"]][0] == "gender"
    saved = json.loads((folder / "state.json").read_text(encoding="utf-8"))
    assert [c["speaker"] for c in saved["cues"]] == ["S1", "S2"] and len(saved["speakers"]) == 2

    goi.clear()
    chay({"engine": "google", "gender_split": True})
    assert not goi, "đã có vai rồi thì không tách lại, kẻo mất nhãn người dùng đã sửa"
