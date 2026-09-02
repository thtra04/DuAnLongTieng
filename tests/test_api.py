"""Kiểm thử API — chạy bằng TestClient, không cần khởi động server thật."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


# ------------------------------------------------------------ /api/system


def test_system_bao_trang_thai_nhan_dien_nguoi_noi(client):
    data = client.get("/api/system").json()
    assert "diarize" in data
    dia = data["diarize"]
    assert set(dia) >= {"available", "reason", "has_token", "model"}
    assert isinstance(dia["available"], bool)
    # Không dùng được thì PHẢI nói lý do, nếu không giao diện chỉ hiện ô xám câm
    if not dia["available"]:
        assert dia["reason"].strip()


def test_system_khong_lo_token(client):
    """`has_token` là cờ true/false — tuyệt đối không trả chính token ra ngoài."""
    raw = client.get("/api/system").text
    assert "hf_" not in raw.lower().replace("hf_token", "")


# ----------------------------------------------------------- /api/analyze


def test_analyze_tu_choi_khi_thieu_video(client):
    r = client.post("/api/analyze", json={"source_type": "file", "media_id": "khong-co"})
    assert r.status_code == 400
    assert "video" in r.json()["error"].lower()


def test_analyze_chan_som_khi_chua_du_dieu_kien_diarize(client, monkeypatch):
    """Thiếu điều kiện thì phải báo NGAY, đừng để chạy xong ASR mới lỗi."""
    from app import diarize

    monkeypatch.setattr(diarize, "available", lambda token="": (False, "Thiếu token thử nghiệm."))
    r = client.post(
        "/api/analyze",
        json={"source_type": "url", "url": "https://example.com/v", "diarize": True},
    )
    assert r.status_code == 400
    assert r.json()["error"] == "Thiếu token thử nghiệm."


def test_analyze_tu_choi_so_nhan_vat_sai_kieu(client, monkeypatch):
    from app import diarize

    monkeypatch.setattr(diarize, "available", lambda token="": (True, ""))
    r = client.post(
        "/api/analyze",
        json={
            "source_type": "url",
            "url": "https://example.com/v",
            "diarize": True,
            "num_speakers": "ba người",
        },
    )
    assert r.status_code == 400
    assert "nhân vật" in r.json()["error"]


def test_analyze_tu_choi_link_khong_phai_http(client):
    r = client.post("/api/analyze", json={"source_type": "url", "url": ""})
    assert r.status_code == 400


def test_analyze_tu_choi_nguon_la(client):
    r = client.post("/api/analyze", json={"source_type": "webcam"})
    assert r.status_code == 400


# ------------------------------------------------------------- job / file


def test_job_khong_ton_tai_tra_404(client):
    assert client.get("/api/jobs/khongcothat").status_code == 404


def test_khong_lay_duoc_file_ngoai_thu_muc_job(client):
    """Chặn đi ngược thư mục qua tên file."""
    r = client.get("/api/jobs/khongcothat/files/..%2F..%2Fpyproject.toml")
    assert r.status_code == 404


def test_du_an_khong_ton_tai_tra_404(client):
    assert client.get("/api/projects/khongcothat").status_code == 404
