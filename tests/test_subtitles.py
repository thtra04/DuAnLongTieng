"""Kiểm thử mô hình cue và đọc/ghi SRT · VTT · ASS."""

from __future__ import annotations

import pytest

from backend.core.subtitles import (
    Cue,
    cues_from_words,
    fmt_ass_time,
    fmt_srt_time,
    fmt_vtt_time,
    is_cjk,
    parse_subtitle,
    parse_time,
    shift_cues,
    split_plain_text,
    to_ass,
    to_srt,
    to_vtt,
    wrap_text,
)


# ----------------------------------------------------------- thời gian


@pytest.mark.parametrize(
    "seconds,expected",
    [
        (0, "00:00:00,000"),
        (1.5, "00:00:01,500"),
        (61.25, "00:01:01,250"),
        (3661.001, "01:01:01,001"),
        (-5, "00:00:00,000"),  # âm thì kẹp về 0, không được ra giờ âm
    ],
)
def test_dinh_dang_gio_srt(seconds, expected):
    assert fmt_srt_time(seconds) == expected


def test_vtt_dung_dau_cham_thay_dau_phay():
    assert fmt_vtt_time(61.25) == "00:01:01.250"


def test_ass_dung_phan_tram_giay():
    assert fmt_ass_time(3661.25) == "1:01:01.25"
    assert fmt_ass_time(-1) == "0:00:00.00"


@pytest.mark.parametrize(
    "text,expected",
    [
        ("00:01:01,250", 61.25),
        ("00:01:01.250", 61.25),
        ("01:01.5", 61.5),
        ("12.5", 12.5),
        ("rác", 0.0),
    ],
)
def test_doc_gio(text, expected):
    assert parse_time(text) == pytest.approx(expected)


def test_lam_tron_gio_khong_bi_troi():
    """0,9995 s phải thành 1,000 chứ không phải 0,999 — sai số dồn lại thấy được."""
    assert fmt_srt_time(0.9995) == "00:00:01,000"


# ------------------------------------------------------------- CJK


@pytest.mark.parametrize(
    "text,expected",
    [
        ("你好世界", True),
        ("こんにちは", True),
        ("안녕하세요", True),
        ("Xin chào các bạn", False),
        ("", False),
        ("   ", False),
        ("Hello 你好世界啊", True),   # quá 30% là chữ Hán
        ("Xin chào thế giới rộng lớn 好", False),
    ],
)
def test_nhan_dien_chu_cjk(text, expected):
    assert is_cjk(text) is expected


# --------------------------------------------------------- ngắt dòng


def test_khong_ngat_khi_du_ngan():
    assert wrap_text("Xin chào", 42) == "Xin chào"


def test_giu_dung_gioi_han_ky_tu():
    """Thanh trượt số ký tự phải có tác dụng thật — từng có bug làm nó vô nghĩa."""
    text = "Đây là một câu tiếng Việt khá dài dùng để kiểm tra việc ngắt dòng tự động"
    for limit in (20, 30, 42):
        lines = wrap_text(text, limit).split("\n")
        assert all(len(ln) <= limit for ln in lines), f"vượt giới hạn {limit}: {lines}"


def test_gioi_han_nho_hon_cho_ra_nhieu_dong_hon():
    text = "Đây là một câu tiếng Việt khá dài dùng để kiểm tra việc ngắt dòng tự động"
    assert len(wrap_text(text, 20).split("\n")) > len(wrap_text(text, 42).split("\n"))


def test_tu_dai_hon_ca_gioi_han_van_bi_che():
    out = wrap_text("A" * 100, 20)
    assert all(len(ln) <= 20 for ln in out.split("\n"))


def test_chu_han_ngat_theo_nua_gioi_han():
    """Một chữ Hán rộng gấp đôi chữ Latin nên một dòng chứa được ít hơn."""
    lines = wrap_text("你好" * 40, 40).split("\n")
    assert all(len(ln) <= 20 for ln in lines)


# --------------------------------------------------------- ghi file


def cues():
    return [Cue(0.0, 2.0, "Xin chào", "Hello"), Cue(2.5, 4.0, "Tạm biệt", "Goodbye")]


def test_srt_dung_dinh_dang():
    out = to_srt(cues())
    assert out.startswith("1\n00:00:00,000 --> 00:00:02,000\nXin chào")
    assert "2\n00:00:02,500 --> 00:00:04,000\nTạm biệt" in out


def test_srt_song_ngu_hai_dong():
    out = to_srt(cues(), mode="both")
    assert "Xin chào\nHello" in out


def test_srt_chi_ban_dich():
    out = to_srt(cues(), mode="second")
    assert "Hello" in out and "Xin chào" not in out


def test_srt_danh_so_lien_tuc_khi_bo_cue_rong():
    """Bỏ cue rỗng mà vẫn giữ số thứ tự cũ thì trình phát báo file hỏng."""
    data = [Cue(0, 1, "một"), Cue(1, 2, "  "), Cue(2, 3, "ba")]
    numbers = [ln for ln in to_srt(data).splitlines() if ln.strip().isdigit()]
    assert numbers == ["1", "2"]


def test_vtt_co_dong_dau():
    assert to_vtt(cues()).startswith("WEBVTT")


def test_ass_co_do_phan_giai_va_thoai():
    out = to_ass(cues(), play_res_x=1280, play_res_y=720)
    assert "PlayResX: 1280" in out and "PlayResY: 720" in out
    assert out.count("Dialogue:") == 2


def test_ass_thoat_ky_tu_dac_biet():
    """`{}` trong ASS là cú pháp thẻ lệnh — không thoát là hỏng cả dòng."""
    out = to_ass([Cue(0, 1, "giá {khuyến mãi} 50%")])
    assert "\\{khuyến mãi\\}" in out


def test_ass_xuong_dong_thanh_ky_hieu_N():
    out = to_ass([Cue(0, 1, "một câu rất dài cần phải ngắt xuống dòng")], max_chars=12)
    assert "\\N" in out


def test_co_chu_scale_theo_do_phan_giai():
    """Cỡ chữ người dùng đặt theo khung 1080p, lên 4K phải to lên tương ứng."""
    small = to_ass([Cue(0, 1, "a")], style={"size": 40}, play_res_y=1080)
    big = to_ass([Cue(0, 1, "a")], style={"size": 40}, play_res_y=2160)
    assert "Default,Arial,40," in small
    assert "Default,Arial,80," in big


# ---------------------------------------------------------- đọc file


def test_doc_srt():
    raw = "1\n00:00:01,000 --> 00:00:03,500\nXin chào\n\n2\n00:00:04,000 --> 00:00:05,000\nTạm biệt\n"
    out = parse_subtitle(raw)
    assert len(out) == 2
    assert out[0].start == 1.0 and out[0].end == 3.5
    assert out[0].text == "Xin chào"


def test_doc_vtt_va_bo_the_html():
    raw = "WEBVTT\n\n00:00:01.000 --> 00:00:02.000\n<i>Nghiêng</i> và <c.x>màu</c>\n"
    out = parse_subtitle(raw)
    assert out[0].text == "Nghiêng và màu"


def test_doc_file_co_bom_va_xuong_dong_windows():
    raw = "﻿1\r\n00:00:01,000 --> 00:00:02,000\r\nXin chào\r\n"
    assert parse_subtitle(raw)[0].text == "Xin chào"


def test_doc_file_rong_hoac_sai_dinh_dang():
    assert parse_subtitle("") == []
    assert parse_subtitle("đây không phải phụ đề") == []


def test_ghi_roi_doc_lai_khong_mat_gi():
    goc = cues()
    lai = parse_subtitle(to_srt(goc))
    assert [c.text for c in lai] == [c.text for c in goc]
    assert [round(c.start, 3) for c in lai] == [round(c.start, 3) for c in goc]


# ------------------------------------------------------ tách văn bản


def test_tach_cau_theo_dau_cham():
    out = split_plain_text("Câu một. Câu hai! Câu ba?")
    assert out == ["Câu một.", "Câu hai!", "Câu ba?"]


def test_tach_bo_dong_trong():
    assert split_plain_text("Một\n\n\nHai") == ["Một", "Hai"]


# ------------------------------------------- gom từ thành cue


def words(*items):
    return [{"word": w, "start": s, "end": e} for w, s, e in items]


def test_ngat_cue_o_dau_cham_cau():
    out = cues_from_words(words(("Xin ", 0, 0.5), ("chào. ", 0.5, 1.0), ("Tạm ", 1.1, 1.5), ("biệt.", 1.5, 2.0)))
    assert len(out) == 2
    assert out[0].text == "Xin chào."


def test_ngat_cue_o_khoang_lang_dai():
    out = cues_from_words(words(("một", 0, 0.5), ("hai", 5.0, 5.5)))
    assert len(out) == 2


def test_cue_khong_bao_gio_chong_lan():
    out = cues_from_words(words(("một", 0, 0.5), ("hai", 0.55, 1.0), ("ba", 3.0, 3.5)))
    for a, b in zip(out, out[1:]):
        assert a.end <= b.start, "cue chồng lấn làm phụ đề nhảy loạn khi phát"


def test_cue_co_do_dai_toi_thieu():
    out = cues_from_words(words(("a", 0.0, 0.05)))
    assert out[0].end - out[0].start >= 0.7


def test_bo_qua_tu_rong():
    out = cues_from_words(words(("  ", 0, 0.5), ("thật", 1.0, 1.5)))
    assert len(out) == 1 and out[0].text == "thật"


def test_khong_co_tu_nao():
    assert cues_from_words([]) == []


# ------------------------------------------------------------ dời giờ


def test_doi_gio_toan_bo():
    data = cues()
    shift_cues(data, 1.5)
    assert data[0].start == 1.5 and data[0].end == 3.5


def test_doi_gio_am_khong_ra_so_am():
    data = [Cue(0.5, 1.0, "a")]
    shift_cues(data, -10)
    assert data[0].start == 0.0
    assert data[0].end > data[0].start


# ------------------------------------------------------- Cue dict


def test_cue_chuyen_qua_lai_dict():
    goc = Cue(1.2345, 2.5, " chữ ", " dịch ", speaker="S1")
    lai = Cue.from_dict(goc.to_dict())
    assert lai.text == "chữ" and lai.text2 == "dịch"
    assert lai.speaker == "S1"
    assert lai.start == pytest.approx(1.234, abs=0.001)


def test_cue_from_dict_thieu_khoa():
    c = Cue.from_dict({})
    assert c.start == 0.0 and c.text == "" and c.speaker == ""
