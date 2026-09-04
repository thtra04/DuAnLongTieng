"""Kiểm thử canh văn bản người dùng vào timeline, và nới giờ theo tốc độ đọc."""

from __future__ import annotations

import pytest

from backend.core.align import CPS_CJK, CPS_LATIN, MAX_STRETCH, align_text, retime_translation
from backend.core.subtitles import Cue


def words(*items):
    return [{"word": w, "start": s, "end": e} for w, s, e in items]


# --------------------------------------------------------- canh văn bản


def test_canh_dung_moc_gio_khi_chu_khop_han():
    asr = words(("Xin", 1.0, 1.4), ("chào", 1.4, 2.0), ("thế", 5.0, 5.4), ("giới", 5.4, 6.0))
    out = align_text("Xin chào. Thế giới.", asr, total_duration=10)

    assert len(out) == 2
    assert out[0].start == pytest.approx(1.0, abs=0.01)
    assert out[0].end == pytest.approx(2.0, abs=0.01)
    assert out[1].start == pytest.approx(5.0, abs=0.01)


def test_giu_nguyen_van_chu_cua_nguoi_dung():
    """Điểm mấu chốt của chế độ này: chữ là của người dùng, chỉ mượn giờ của ASR."""
    asr = words(("xin", 1.0, 1.4), ("chao", 1.4, 2.0))
    out = align_text("Xin chào các bạn!", asr, total_duration=5)
    assert "".join(c.text for c in out) == "Xin chào các bạn!"


def test_chu_khong_khop_thi_noi_suy_chu_khong_bo():
    asr = words(("hoàn", 1.0, 1.5), ("toàn", 1.5, 2.0), ("khác", 2.0, 2.5))
    out = align_text("Một. Hai. Ba.", asr, total_duration=6)

    assert len(out) == 3
    for a, b in zip(out, out[1:]):
        assert a.end <= b.start
        assert b.start >= a.start


def test_khong_co_timestamp_thi_chia_deu():
    out = align_text("Một. Hai. Ba. Bốn.", [], total_duration=8)
    assert len(out) == 4
    assert out[0].start == pytest.approx(0.0, abs=0.01)
    assert out[-1].end <= 8.5


def test_van_ban_rong_tra_ve_rong():
    assert align_text("", words(("a", 0, 1)), total_duration=5) == []
    assert align_text("   \n  ", words(("a", 0, 1)), total_duration=5) == []


def test_cue_khong_bao_gio_chong_lan_sau_khi_canh():
    asr = words(*[(f"t{i}", i * 0.5, i * 0.5 + 0.4) for i in range(20)])
    out = align_text(". ".join(f"Câu số {i}" for i in range(10)) + ".", asr, total_duration=12)
    for a, b in zip(out, out[1:]):
        assert a.end <= b.start, "cue chồng lấn làm phụ đề nhảy loạn"


def test_cat_nho_cau_qua_dai():
    dai = " ".join(["từ"] * 120) + "."
    out = align_text(dai, [], total_duration=30, max_chars=40)
    assert len(out) > 1
    assert all(c.end > c.start for c in out)


def test_moc_gio_luon_tang_dan():
    out = align_text("Một. Hai. Ba. Bốn. Năm.", [], total_duration=10)
    starts = [c.start for c in out]
    assert starts == sorted(starts)


# ---------------------------------------------------- nới theo tốc độ đọc


def test_noi_cue_hien_qua_nhanh():
    """40 ký tự Latin cần ~2,35s mới đọc kịp; cue chỉ dài 0,5s -> phải nới."""
    text = "A" * 40
    data = [Cue(0.0, 0.5, text), Cue(10.0, 12.0, "sau")]
    retime_translation(data)
    assert data[0].end > 0.5
    assert data[0].end == pytest.approx(len(text) / CPS_LATIN, abs=0.05)


def test_khong_lan_sang_cue_ke_tiep():
    data = [Cue(0.0, 0.5, "A" * 40), Cue(1.0, 2.0, "sau")]
    retime_translation(data)
    assert data[0].end <= data[1].start, "nới lấn sang câu sau là chữ đè lên nhau"


def test_khong_noi_qua_muc_toi_da():
    data = [Cue(0.0, 0.5, "A" * 500)]
    retime_translation(data)
    assert data[0].end - 0.5 <= MAX_STRETCH + 0.001


def test_cue_da_du_dai_thi_khong_dong_toi():
    data = [Cue(0.0, 10.0, "ngắn")]
    retime_translation(data)
    assert data[0].end == 10.0


def test_moc_bat_dau_khong_bao_gio_bi_doi():
    """Dời mốc đầu là chữ lệch khỏi lời thoại — chỉ được kéo dài phần đuôi."""
    data = [Cue(3.0, 3.2, "A" * 40)]
    retime_translation(data)
    assert data[0].start == 3.0


def test_chu_han_duoc_tinh_toc_do_doc_cham_hon():
    # Cue kế tiếp đặt xa để `room` không phải là thứ chặn — ở đây chỉ đo tốc độ đọc
    han = [Cue(0.0, 0.3, "字" * 12), Cue(60.0, 61.0, "sau")]
    latin = [Cue(0.0, 0.3, "a" * 12), Cue(60.0, 61.0, "sau")]
    retime_translation(han)
    retime_translation(latin)
    assert han[0].end > latin[0].end, "chữ Hán đọc chậm hơn nên phải được nới nhiều hơn"
    assert han[0].end == pytest.approx(12 / CPS_CJK, abs=0.05)
    assert latin[0].end == pytest.approx(12 / CPS_LATIN, abs=0.05)


def test_uu_tien_ban_dich_khi_do_do_dai():
    """Cue hiện bản dịch thì phải đo theo bản dịch, không theo lời gốc."""
    theo_goc = [Cue(0.0, 0.5, "ngắn"), Cue(60.0, 61.0, "sau")]
    theo_dich = [Cue(0.0, 0.5, "ngắn", "B" * 30), Cue(60.0, 61.0, "sau")]
    retime_translation(theo_goc)
    retime_translation(theo_dich)
    assert theo_dich[0].end > theo_goc[0].end


def test_cue_rong_khong_gay_loi():
    data = [Cue(0.0, 1.0, "", "")]
    retime_translation(data)
    assert data[0].end == 1.0


def test_danh_sach_rong():
    assert retime_translation([]) == []
