"""Kiểm thử phần điều phối của pipeline: dựng danh sách bước, cảnh báo, tiện ích."""

from __future__ import annotations

import pytest

from app import dubbing, pipeline
from app.pipeline import (
    _coverage_warning,
    _fallback_voice,
    _hms,
    _voice_label,
    _warn_too_many_lines,
    analyze_steps,
    render_steps,
    safe_stem,
    write_utf8,
)
from app.subtitles import Cue


class JobGia:
    """Job giả chỉ để hứng log."""

    def __init__(self):
        self.logs: list[str] = []

    def log(self, msg):
        self.logs.append(msg)

    def __contains__(self, text):
        return any(text in ln for ln in self.logs)


# ------------------------------------------------------ bước phân tích


def keys(cfg):
    return [s.key for s in analyze_steps(cfg)]


def test_nguon_la_file_thi_khong_co_buoc_tai():
    assert "download" not in keys({"source_type": "file", "sub_mode": "auto"})


def test_nguon_la_link_thi_co_buoc_tai():
    assert keys({"source_type": "url", "sub_mode": "auto"})[0] == "download"


def test_nhan_tu_file_srt_thi_khong_can_nghe():
    ks = keys({"sub_mode": "srt"})
    assert "subs" in ks
    assert "audio" not in ks and "asr" not in ks


def test_che_do_theo_van_ban_co_them_buoc_canh():
    assert "align" in keys({"sub_mode": "text"})
    assert "align" not in keys({"sub_mode": "auto"})


def test_buoc_dich_chi_co_khi_bat_dich():
    assert "translate" in keys({"sub_mode": "auto", "translate": True})
    assert "translate" not in keys({"sub_mode": "auto"})


def test_buoc_nhan_dien_nguoi_noi_chi_co_khi_bat():
    assert "diarize" in keys({"sub_mode": "auto", "diarize": True})
    assert "diarize" not in keys({"sub_mode": "auto"})


def test_nhan_dien_nguoi_noi_chay_sau_khi_nghe_loi_thoai():
    """Phải có cue rồi mới gán nhãn được, nên diarize buộc phải sau asr."""
    ks = keys({"sub_mode": "auto", "diarize": True, "translate": True})
    assert ks.index("asr") < ks.index("diarize") < ks.index("translate")


def test_nhan_dien_nguoi_noi_chay_duoc_ca_khi_nap_san_srt():
    ks = keys({"sub_mode": "srt", "diarize": True})
    assert "diarize" in ks


def test_luon_ket_bang_buoc_ghi_file():
    assert keys({"sub_mode": "auto", "translate": True, "diarize": True})[-1] == "write"


def test_nhan_buoc_tai_ghi_ro_so_phan():
    steps = analyze_steps({"source_type": "url", "part": 7, "sub_mode": "auto"})
    assert "phần 7" in steps[0].label


# --------------------------------------------------------- bước xuất


def rkeys(cfg):
    return [s.key for s in render_steps(cfg)]


def test_chi_xuat_chu_thi_mot_buoc():
    assert rkeys({"outputs": {"srt": True}}) == ["files"]


def test_nung_phu_de_them_buoc_burn():
    assert "burn" in rkeys({"outputs": {"burn": True}})


def test_long_tieng_them_hai_buoc():
    ks = rkeys({"outputs": {"dub": True}, "dub": {"voice": "abc"}})
    assert "tts" in ks and "dubmux" in ks
    assert "ref" not in ks, "giọng dựng sẵn thì không cần cắt mẫu"


def test_giong_chung_la_nhan_ban_thi_can_buoc_cat_mau():
    ks = rkeys({"outputs": {"dub": True}, "dub": {"voice": dubbing.CLONE_VOICE}})
    assert "ref" in ks


def test_chi_mot_nhan_vat_chon_nhan_ban_cung_can_buoc_cat_mau():
    """Ca dễ sót: giọng chung là dựng sẵn nhưng một vai lại chọn nhân bản."""
    ks = rkeys({
        "outputs": {"dub": True},
        "dub": {"voice": "giong_thuong", "voices": {"S1": "a", "S2": dubbing.CLONE_VOICE}},
    })
    assert "ref" in ks


def test_khong_vai_nao_nhan_ban_thi_khong_co_buoc_cat_mau():
    ks = rkeys({
        "outputs": {"dub": True},
        "dub": {"voice": "giong_thuong", "voices": {"S1": "a", "S2": "b"}},
    })
    assert "ref" not in ks


def test_cat_mau_chay_truoc_khi_doc():
    ks = rkeys({"outputs": {"dub": True}, "dub": {"voice": dubbing.CLONE_VOICE}})
    assert ks.index("ref") < ks.index("tts") < ks.index("dubmux")


# ---------------------------------------------------------- tên file


@pytest.mark.parametrize(
    "goc,mong_doi",
    [
        ("phim hay.mp4", "phim hay"),
        ("phim<>:hay.mp4", "phimhay"),
        ("../../etc/passwd", "passwd"),
        ("", "video"),
        ("...", "video"),
    ],
)
def test_lam_sach_ten_file(goc, mong_doi):
    assert safe_stem(goc) == mong_doi


def test_ten_file_bi_cat_khi_qua_dai():
    assert len(safe_stem("x" * 200)) <= 60


def test_ten_file_giu_duoc_tieng_viet():
    assert safe_stem("Đại Hán Thiên Mệnh.mp4") == "Đại Hán Thiên Mệnh"


# ---------------------------------------------------------- ghi file


def test_ghi_utf8_dung_xuong_dong_LF(workdir):
    """Path.write_text đổi \\n thành \\r\\n trên Windows, làm hỏng mốc giờ SRT."""
    path = write_utf8(workdir / "a.srt", "một\nhai\n")
    assert path.read_bytes() == "một\nhai\n".encode()
    assert b"\r\n" not in path.read_bytes()


# --------------------------------------------------------- định dạng giờ


@pytest.mark.parametrize(
    "giay,mong_doi",
    [(0, "0:00"), (59, "0:59"), (60, "1:00"), (3599, "59:59"), (3600, "1:00:00"), (33075, "9:11:15")],
)
def test_dinh_dang_gio_cho_nguoi_doc(giay, mong_doi):
    assert _hms(giay) == mong_doi


def test_gio_khong_hop_le():
    assert _hms(None) == "0:00"


# ------------------------------------------------------- cảnh báo phủ


def test_khong_canh_bao_khi_phu_du():
    job = JobGia()
    assert _coverage_warning(job, {"coverage": 0.95}, 100) == ""
    assert job.logs == []


def test_canh_bao_khi_phu_thap():
    job = JobGia()
    msg = _coverage_warning(job, {"coverage": 0.30, "gaps": [(30, 100)]}, 100)
    assert "30%" in msg
    assert "30–100s" in job


def test_khong_canh_bao_khi_khong_biet_thoi_luong():
    job = JobGia()
    assert _coverage_warning(job, {"coverage": 0.1}, 0) == ""


def test_bo_qua_khoang_trong_ngan():
    job = JobGia()
    _coverage_warning(job, {"coverage": 0.3, "gaps": [(10, 15)]}, 100)
    assert "10–15s" not in job


# ------------------------------------------------- cảnh báo quá nhiều dòng


def test_canh_bao_khi_phai_xuong_qua_nhieu_dong():
    job = JobGia()
    cues = [Cue(0, 3, "từ " * 40)]
    _warn_too_many_lines(job, cues, "main", "vi", None, max_chars=20, max_lines=2)
    assert "1/1 dòng" in job


def test_khong_canh_bao_khi_dong_du_ngan():
    job = JobGia()
    _warn_too_many_lines(job, [Cue(0, 3, "ngắn")], "main", "vi", None, 42, 2)
    assert job.logs == []


# ------------------------------------------------------ giọng dự phòng


def test_giong_dung_san_duoc_giu_nguyen():
    assert _fallback_voice("giong_nam_bac") == "giong_nam_bac"


def test_giong_nhan_ban_khong_duoc_truyen_thang_vao_engine(monkeypatch):
    """`__clone__` không phải id giọng thật — đưa vào engine là lỗi từng câu."""
    monkeypatch.setattr(dubbing, "list_voices", lambda: [{"id": "vai_a", "label": "A"}])
    assert _fallback_voice(dubbing.CLONE_VOICE) == "vai_a"


def test_khong_lay_duoc_danh_sach_giong_thi_de_engine_tu_chon(monkeypatch):
    monkeypatch.setattr(dubbing, "list_voices", lambda: (_ for _ in ()).throw(RuntimeError()))
    assert _fallback_voice(dubbing.CLONE_VOICE) == ""


def test_nhan_giong_de_doc():
    assert _voice_label(dubbing.CLONE_VOICE) == "nhân bản giọng gốc"
    assert _voice_label("vai_a") == "vai_a"


def test_ten_toan_dau_cham_hoac_khoang_trang_thi_dung_ten_du_phong():
    for goc in ("...", "   ", " . ", ".."):
        assert safe_stem(goc) == "video", f"{goc!r} không được thành tên file"
