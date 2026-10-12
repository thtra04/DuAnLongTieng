"""Kiểm thử dò & che phụ đề nung sẵn (backend/core/hardsub.py).

Khung hình tổng hợp: nền có vân, "phụ đề" là các nét trắng mảnh viền đen ở một
dải ngang, đổi nội dung theo từng câu — đúng như phụ đề thật. Ngưỡng của bộ dò
được chọn trên video thật (3 video có phụ đề, 2 bản cắt bỏ phụ đề; xem docstring
của module); ở đây giữ cho các trường hợp then chốt không bị hỏng về sau.
"""

from __future__ import annotations

import numpy as np
import pytest

from backend.core import hardsub
from backend.core.pipeline import analyze_steps
from backend.core.subtitles import Cue

H, W = 270, 480


def _scene(rng, busy: bool = False) -> np.ndarray:
    """Nền: mảng màu trung bình, có thêm hình khối viền đen nếu `busy` (kiểu hoạt hình)."""
    f = np.full((H, W), 90, np.uint8) + rng.integers(0, 25, (H, W), dtype=np.uint8)
    if busy:
        for _ in range(30):
            y, x = rng.integers(0, H - 30), rng.integers(0, W - 30)
            hh, ww = rng.integers(10, 30, 2)
            f[y:y + hh, x:x + ww] = 225                      # mảng sáng to (áo trắng)
            f[y:y + hh, x] = f[y:y + hh, x + ww - 1] = 20    # viền đen
            f[y, x:x + ww] = f[y + hh - 1, x:x + ww] = 20
    return f


def _text(f: np.ndarray, rng, y0: int, center: float = 0.5, n: int = 9, seed_text=None) -> None:
    """Vẽ một "câu" phụ đề: n chữ, mỗi chữ vài nét trắng mảnh có viền đen."""
    r = np.random.default_rng(seed_text) if seed_text is not None else rng
    cw, gap = 14, 3
    x0 = int(center * W - n * (cw + gap) / 2)
    for k in range(n):
        cx = x0 + k * (cw + gap)
        for _ in range(4):
            if r.random() < 0.5:   # nét ngang
                yy, xa = y0 + r.integers(1, 12), cx + r.integers(0, 6)
                f[yy - 1:yy + 2, xa - 1:xa + 9] = 15
                f[yy, xa:xa + 8] = 250
            else:                  # nét dọc
                xx, ya = cx + r.integers(1, 12), y0 + r.integers(0, 5)
                f[ya - 1:ya + 9, xx - 1:xx + 2] = 15
                f[ya:ya + 8, xx] = 250


def _frames(text=True, busy=False, center=0.5, same_text=False, n=20, y0=215):
    rng = np.random.default_rng(3)
    out = []
    for i in range(n):
        f = _scene(rng, busy)
        if text:
            _text(f, rng, y0, center, seed_text=7 if same_text else None)
        out.append(f)
    return out


# ------------------------------------------------------------------ dò


def test_tim_dung_dai_phu_de_doi_chu_theo_cau():
    r = hardsub.find_band(_frames())
    assert r["found"], r
    assert r["y0"] <= 214 / H and 228 / H <= r["y1"], "dải phải trùm hết dòng chữ (hàng 214–228)"
    assert r["y1"] - r["y0"] < 0.2
    assert r["x0"] < 0.4 and r["x1"] > 0.6 and abs((r["x0"] + r["x1"]) / 2 - 0.5) < 1e-3


def test_tim_duoc_ca_tren_nen_hoat_hinh_nhieu_net():
    r = hardsub.find_band(_frames(busy=True))
    assert r["found"] and r["y0"] <= 215 / H <= r["y1"], r


def test_khong_co_phu_de_thi_khong_bao_nham():
    assert not hardsub.find_band(_frames(text=False))["found"]
    assert not hardsub.find_band(_frames(text=False, busy=True))["found"]


def test_logo_dung_yen_khong_phai_phu_de():
    """Chữ không đổi qua các câu (logo, tên kênh) thì không che — nó không phải phụ đề."""
    assert not hardsub.find_band(_frames(same_text=True))["found"]


def test_chu_lech_mot_ben_khong_phai_phu_de():
    r = hardsub.find_band(_frames(center=0.2))
    assert not r["found"] and "canh giữa" in r["reason"]


def test_qua_it_cau_thoai_thi_khong_do():
    r = hardsub.find_band(_frames(n=3))
    assert not r["found"] and "Quá ít" in r["reason"]


def test_net_manh_moi_tinh_mang_sang_to_thi_bo():
    f = np.full((60, 60), 80, np.uint8)
    f[10:40, 10:40] = 230                     # mảng sáng to viền đen
    f[10:40, 9] = f[10:40, 40] = 10
    f[50, 5:55] = 250                         # nét chữ mảnh viền đen
    f[49, 5:55] = f[51, 5:55] = 10
    m = hardsub.text_mask(f)
    assert m[50, 10:50].all(), "nét mảnh phải được giữ"
    assert not m[15:35, 15:35].any(), "lòng mảng sáng to không phải nét chữ"


def test_moc_lay_khung_o_giua_cau_va_gioi_han_so_luong():
    cues = [Cue(i * 2.0, i * 2.0 + 1.5, "x") for i in range(100)] + [Cue(500, 500.3, "ngắn")]
    t = hardsub.sample_times(cues)
    assert len(t) == hardsub.MAX_FRAMES and t == sorted(t)
    assert t[0] == 0.75 and 500.15 not in t


# ------------------------------------------------------------------ che


def test_clean_mask_kiem_tra_dau_vao():
    assert hardsub.clean_mask(None) is None
    assert hardsub.clean_mask({"mode": "xoa", "y0": 0.8, "y1": 0.9}) is None
    assert hardsub.clean_mask({"mode": "blur", "y0": "a", "y1": 0.9}) is None
    assert hardsub.clean_mask({"mode": "blur", "y0": 0.8, "y1": 0.801}) is None, "dải quá mỏng"
    m = hardsub.clean_mask({"mode": "box", "y0": 1.4, "y1": 0.8, "x0": -1, "x1": 0.7})
    assert m == {"mode": "box", "y0": 0.8, "y1": 1.0, "x0": 0.0, "x1": 0.7}


@pytest.mark.parametrize("mode,dark", [("blur", "0.28"), ("box", "0.85")])
def test_bo_loc_che_dung_toa_do_chan(mode, dark):
    vf = hardsub.mask_filter({"mode": mode, "y0": 0.77, "y1": 0.84, "x0": 0.3, "x1": 0.7}, 1920, 1080)
    assert "crop=768:76:576:830" in vf and "gblur" in vf and f"black@{dark}" in vf
    assert vf.endswith("overlay=576:830"), "một đầu ra để nối tiếp bộ lọc subtitles"


def test_nung_co_che_thi_bo_loc_che_dung_truoc_phu_de(tmp_path, monkeypatch):
    from backend.core import media

    seen = {}
    monkeypatch.setattr(media, "probe", lambda v: {"duration": 5.0, "width": 1280, "height": 720})
    monkeypatch.setattr(media, "run_ffmpeg_progress", lambda args, dur, cb, cwd=None: seen.update(args=args))
    ass = tmp_path / "burn.ass"
    ass.write_text("x", encoding="utf-8")
    mask = {"mode": "blur", "y0": 0.77, "y1": 0.84, "x0": 0.3, "x1": 0.7}
    media.burn_subtitles(tmp_path / "v.mp4", ass, tmp_path / "o.mp4", mask=mask)
    vf = seen["args"][seen["args"].index("-vf") + 1]
    assert vf.index("gblur") < vf.index("subtitles=burn.ass")

    media.burn_subtitles(tmp_path / "v.mp4", ass, tmp_path / "o.mp4")
    assert seen["args"][seen["args"].index("-vf") + 1] == "subtitles=burn.ass"


def test_buoc_do_luon_co_khi_phan_tich():
    keys = [s.key for s in analyze_steps({"source_type": "file", "sub_mode": "auto", "translate": True})]
    assert keys.index("asr") < keys.index("hardsub") < keys.index("translate")


def test_api_do_lai_du_an_khong_ton_tai(tmp_db):
    from fastapi.testclient import TestClient

    from backend.main import app

    with TestClient(app) as client:
        assert client.post("/api/projects/khongco/hardsub").status_code == 404
