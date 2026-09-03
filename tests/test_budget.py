"""Kiểm thử HP-5 — vòng lặp đóng về ngân sách thời gian."""

from __future__ import annotations

import pytest

from app import budget
from app.budget import assess, over_budget, run_loop, target_syllables, window_seconds
from app.duration import DurationModel
from app.subtitles import Cue


def c(start, end, text, text2):
    return Cue(start=start, end=end, text=text, text2=text2)


class MoHinhGia(DurationModel):
    """Mỗi âm tiết 0,25 s — dễ tính bằng tay."""

    def __init__(self):
        super().__init__(weights=[1.0], meta={})

    def predict(self, text):
        from app.duration import syllables
        return syllables(text) * 0.25


def cat_ngan(requests):
    """Bộ rút gọn giả: giữ đúng số âm tiết được yêu cầu."""
    out = []
    for r in requests:
        words = r["text"].split()
        out.append(" ".join(words[: r["target_syllables"]]) + ".")
    return out


# ------------------------------------------------------------ ngân sách


def test_ngan_sach_gom_khung_va_khoang_lang_sau():
    cues = [c(0, 2, "a", "a"), c(5, 6, "b", "b")]
    # khung 2s + (5 - 2 - 0.02) khoảng lặng sau + vào sớm tối đa 0.15 (đầu video: gap_before = 0)
    assert window_seconds(cues, [0]) == pytest.approx(2 + 2.98 + 0.0, abs=1e-6)


def test_cue_cuoi_duoc_cong_hai_giay():
    cues = [c(0, 2, "a", "a")]
    assert window_seconds(cues, [0]) == pytest.approx(2 + (2.0 - 0.02), abs=1e-6)


def test_vao_som_khong_qua_khoang_trong_phia_truoc():
    cues = [c(0, 1, "a", "a"), c(1.05, 2, "b", "b")]
    # gap_before = 0.05 -> lead_in = 0.03
    assert window_seconds(cues, [1]) == pytest.approx((2 - 1.05) + 1.98 + 0.03, abs=1e-6)


def test_ngan_sach_dong_bo_voi_luc_long_tieng():
    """Vòng lặp và TTS phải cùng một cách tính, nếu không 'vừa' bên này 'tràn' bên kia."""
    from app import dubbing
    assert budget.LEAD_IN == dubbing.MAX_LEAD_IN


# ------------------------------------------------------------ đánh giá


def test_danh_gia_tung_nhom():
    # Hai câu riêng (nguồn có dấu chấm) nhưng sát nút (1,1s): câu đầu không mượn
    # được khoảng lặng phía sau. Nguồn không có dấu chấm thì group_cues gộp chung.
    cues = [c(0, 1, "x.", "một hai ba bốn năm sáu bảy tám"), c(1.1, 2, "y.", "ngắn")]
    items = assess(cues, MoHinhGia())
    assert len(items) == 2
    assert items[0]["predicted"] == 2.0 and items[0]["over"] > 0
    assert items[1]["over"] < 0


def test_khoang_lang_phia_sau_duoc_tinh_vao_ngan_sach():
    """Câu dài nhưng sau nó im lặng 4 s thì vẫn vừa — TTS được lấn vào khoảng lặng đó."""
    cues = [c(0, 1, "x", "một hai ba bốn năm sáu bảy tám"), c(5, 6, "y", "ngắn")]
    assert assess(cues, MoHinhGia())[0]["over"] < 0


def test_bo_qua_cue_chua_co_ban_dich():
    cues = [c(0, 1, "x", ""), c(2, 3, "y", "có")]
    assert len(assess(cues, MoHinhGia())) == 1


def test_loc_cau_vuot_co_dung_sai():
    items = [{"budget": 1.0, "ratio": 1.03}, {"budget": 1.0, "ratio": 1.2}, {"budget": 0, "ratio": 9}]
    assert over_budget(items) == [items[1]]


def test_so_am_tiet_muc_tieu_luon_nho_hon_hien_tai():
    it = {"syllables": 10, "budget": 1.0, "predicted": 2.5}
    t = target_syllables(it)
    assert 1 <= t < 10
    assert t == int(10 * 1.0 / 2.5 * 0.92)


# ------------------------------------------------------------ vòng lặp


def test_vong_lap_rut_gon_cau_vuot():
    cues = [c(0, 1.0, "x.", "một hai ba bốn năm sáu bảy tám chín mười"), c(1.05, 6, "y.", "ổn")]
    stats = run_loop(cues, cat_ngan, MoHinhGia())
    assert stats["over_before"] == 1
    assert stats["over_after"] == 0
    assert stats["tightened"] >= 1 and stats["passes"] >= 1
    assert len(cues[0].text2.split()) < 10


def test_khong_dong_toi_cau_da_vua():
    cues = [c(0, 5, "x", "ngắn thôi"), c(10, 11, "y", "ổn")]
    goc = [k.text2 for k in cues]
    stats = run_loop(cues, cat_ngan, MoHinhGia())
    assert stats["over_before"] == 0 and stats["tightened"] == 0
    assert [k.text2 for k in cues] == goc


def test_toi_da_hai_luot():
    cues = [c(0, 0.3, "x", " ".join(["từ"] * 40))]
    goi = []

    def lì(requests):
        goi.append(len(requests))
        return [r["text"] for r in requests]  # không rút gọn gì -> vẫn vượt

    stats = run_loop(cues, lì, MoHinhGia(), max_passes=2)
    assert stats["passes"] == 1, "không rút được gì thì dừng ngay, khỏi gọi API lần hai vô ích"
    assert stats["over_after"] == 1 and stats["unresolved"]


def test_hai_luot_khi_luot_dau_chua_du():
    cues = [c(0, 0.5, "x", " ".join(["từ"] * 20))]

    def cat_tung_chut(requests):
        return [" ".join(r["text"].split()[:-4]) + "." for r in requests]

    stats = run_loop(cues, cat_tung_chut, MoHinhGia(), max_passes=2)
    assert stats["passes"] == 2


def test_khong_co_cach_rut_gon_thi_chi_do_va_bao():
    cues = [c(0, 0.5, "x", " ".join(["từ"] * 20))]
    log = []
    stats = run_loop(cues, None, MoHinhGia(), on_log=log.append)
    assert stats["over_before"] == 1 and stats["over_after"] == 1
    assert stats["unresolved"][0]["lines"] == "1"
    assert any("atempo" in ln for ln in log)


def test_ban_dich_rut_gon_duoc_chia_lai_vao_tung_cue():
    # cue 0 và 1 là hai mảnh của MỘT câu (nguồn chỉ kết thúc ở cue 1) -> một nhóm;
    # cue 2 là câu khác, sát nút để nhóm đầu không mượn được khoảng lặng.
    cues = [
        c(0.0, 0.5, "aaaa", "một hai ba bốn năm"),
        c(0.5, 1.0, "bbbb.", "sáu bảy tám chín mười"),
        c(1.05, 10, "c.", "ổn"),
    ]
    from app.duration import syllables

    truoc = syllables(cues[0].text2) + syllables(cues[1].text2)
    stats = run_loop(cues, cat_ngan, MoHinhGia())
    assert stats["over_before"] == 1 and stats["tightened"] == 1
    assert cues[0].text2 and cues[1].text2, "cả hai cue của nhóm đều phải còn chữ"
    assert syllables(cues[0].text2) + syllables(cues[1].text2) < truoc


def test_loi_cua_bo_rut_gon_khong_lam_sap():
    cues = [c(0, 0.3, "x", " ".join(["từ"] * 30))]

    def hong(requests):
        raise RuntimeError("API chết")

    stats = run_loop(cues, hong, MoHinhGia())
    assert stats["over_after"] == 1


def test_bao_khi_chua_co_mo_hinh_that():
    cues = [c(0, 5, "x", "ngắn")]
    log = []
    stats = run_loop(cues, None, DurationModel(), on_log=log.append)
    assert stats["model_trained"] is False
    assert any("ước lượng thô" in ln for ln in log)
