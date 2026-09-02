"""Kiểm thử suy mã bộ phim từ link.

Mã bộ quyết định các tập cùng một phim có gom về một chỗ hay không. Suy sai thì
hai phim khác nhau bị nhập làm một, hoặc các tập cùng phim nằm rải rác.
"""

from __future__ import annotations

from app.series import STANDALONE, key_for


# ------------------------------------------------------------ bilibili


def test_bilibili_cac_phan_cung_ma_BV_gom_lam_mot():
    a = key_for("https://www.bilibili.com/video/BV1xx411c7mD?p=1")
    b = key_for("https://www.bilibili.com/video/BV1xx411c7mD?p=27")
    assert a == b == "bilibili:BV1xx411c7mD"


def test_bilibili_hai_ma_BV_khac_nhau_khong_gom():
    a = key_for("https://www.bilibili.com/video/BV1xx411c7mD")
    b = key_for("https://www.bilibili.com/video/BV1yy411c7mE")
    assert a != b


def test_bilibili_bo_qua_tham_so_theo_doi():
    a = key_for("https://www.bilibili.com/video/BV1xx411c7mD?spm_id_from=333.999&vd_source=abc")
    b = key_for("https://www.bilibili.com/video/BV1xx411c7mD")
    assert a == b


# ------------------------------------------------------------- YouTube


def test_youtube_playlist_uu_tien_hon_ma_video():
    a = key_for("https://www.youtube.com/watch?v=aaa111&list=PLxyz")
    b = key_for("https://www.youtube.com/watch?v=bbb222&list=PLxyz")
    assert a == b == "yt-list:PLxyz"


def test_youtube_video_le():
    assert key_for("https://www.youtube.com/watch?v=aaa111") == "yt:aaa111"


def test_youtube_dang_rut_gon():
    assert key_for("https://youtu.be/aaa111") == "yt:aaa111"


def test_youtube_hai_video_khac_nhau_khong_gom():
    assert key_for("https://youtu.be/aaa111") != key_for("https://youtu.be/bbb222")


# ---------------------------------------------------------- link khác


def test_khong_co_link_thi_la_video_le():
    assert key_for("") == STANDALONE
    assert key_for("   ") == STANDALONE
    assert key_for(None) == STANDALONE


def test_bo_tham_so_chi_so_tap_va_theo_doi():
    a = key_for("https://phim.example.com/tap?id=99&p=3&from=search&t=120")
    b = key_for("https://phim.example.com/tap?id=99")
    assert a == b


def test_giu_lai_tham_so_phan_biet_phim():
    """Bỏ hết tham số thì hai phim khác nhau bị nhập một — chỉ được bỏ nhóm đã liệt kê."""
    a = key_for("https://phim.example.com/xem?id=99")
    b = key_for("https://phim.example.com/xem?id=100")
    assert a != b


def test_khong_phan_biet_hoa_thuong_o_ten_mien():
    a = key_for("https://Phim.Example.COM/tap")
    b = key_for("https://phim.example.com/tap")
    assert a == b


def test_bo_dau_gach_cheo_cuoi():
    assert key_for("https://phim.example.com/tap/") == key_for("https://phim.example.com/tap")


def test_bo_fragment():
    a = key_for("https://phim.example.com/tap#binh-luan")
    b = key_for("https://phim.example.com/tap")
    assert a == b


def test_link_hong_khong_lam_no_chuong_trinh():
    assert key_for("http://[không-hợp-lệ").startswith("url:")


def test_ket_qua_luon_on_dinh():
    url = "https://phim.example.com/tap?b=2&a=1"
    assert key_for(url) == key_for(url)
