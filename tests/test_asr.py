"""Kiểm thử phần đo độ phủ của nhận dạng lời thoại.

Whisper có thể bỏ sót cả đoạn dài **mà không báo lỗi**. Mấy hàm đo dưới đây là
thứ duy nhất phát hiện ra chuyện đó, nên chúng phải đúng.
"""

from __future__ import annotations

import pytest

from app.asr import _collect, _is_cuda_failure, coverage, find_gaps, voiced_time


def seg(start, end, text="chữ", **kw):
    return {"start": start, "end": end, "text": text, **kw}


# -------------------------------------------------------- thời gian có lời


def test_cong_don_cac_doan_roi():
    assert voiced_time([seg(0, 2), seg(5, 8)]) == 5.0


def test_gop_doan_chong_lan_khong_dem_hai_lan():
    assert voiced_time([seg(0, 5), seg(3, 8)]) == 8.0


def test_gop_doan_lien_ke_sat_nhau():
    assert voiced_time([seg(0, 5), seg(5.005, 8)]) == pytest.approx(8.0)


def test_doan_nam_gon_trong_doan_khac():
    assert voiced_time([seg(0, 10), seg(2, 4)]) == 10.0


def test_khong_phu_thuoc_thu_tu_dau_vao():
    assert voiced_time([seg(5, 8), seg(0, 2)]) == voiced_time([seg(0, 2), seg(5, 8)])


def test_danh_sach_rong():
    assert voiced_time([]) == 0.0


# ------------------------------------------------------------- độ phủ


def test_phu_tinh_theo_moc_ket_thuc_xa_nhat():
    assert coverage([seg(0, 30)], 100) == 0.3


def test_phu_khong_vuot_qua_mot():
    assert coverage([seg(0, 200)], 100) == 1.0


def test_khong_co_doan_nao_thi_phu_bang_khong():
    assert coverage([], 100) == 0.0


def test_khong_biet_thoi_luong_thi_phu_bang_khong():
    assert coverage([seg(0, 30)], 0) == 0.0


def test_phu_thap_la_dau_hieu_bo_sot():
    """Ca thật: video 9 tiếng nhưng chỉ ra phụ đề vài chục giây đầu."""
    assert coverage([seg(0, 40)], 33000) < 0.01


# ------------------------------------------------------- khoảng trống


def test_tim_khoang_trong_o_giua():
    assert find_gaps([seg(0, 10), seg(60, 70)], 70, min_gap=20) == [(10, 60)]


def test_tim_khoang_trong_o_dau():
    assert find_gaps([seg(30, 40)], 40, min_gap=20) == [(0, 30)]


def test_tim_khoang_trong_o_duoi():
    assert find_gaps([seg(0, 10)], 100, min_gap=20) == [(10, 100)]


def test_bo_qua_khoang_trong_ngan():
    assert find_gaps([seg(0, 10), seg(15, 20)], 20, min_gap=20) == []


def test_khong_co_doan_nao_thi_ca_video_la_khoang_trong():
    assert find_gaps([], 100, min_gap=20) == [(0, 100)]


def test_khoang_trong_khong_bi_lech_vi_doan_chong_lan():
    """Đoạn sau kết thúc sớm hơn đoạn trước — không được sinh khoảng trống ảo."""
    assert find_gaps([seg(0, 50), seg(10, 20)], 60, min_gap=20) == []


def test_video_phu_kin_thi_khong_co_khoang_trong():
    assert find_gaps([seg(0, 100)], 100, min_gap=20) == []


# ------------------------------------------------------- lỗi CUDA


@pytest.mark.parametrize(
    "msg",
    [
        "Library cublas64_12.dll is not found",
        "cuDNN error: CUDNN_STATUS_NOT_INITIALIZED",
        "CUDA out of memory",
        "libcudart.so.12: cannot open shared object file",
        "no GPU detected",
    ],
)
def test_nhan_ra_loi_cuda_de_roi_ve_cpu(msg):
    assert _is_cuda_failure(Exception(msg)) is True


@pytest.mark.parametrize("msg", ["file not found", "invalid audio format", "permission denied"])
def test_loi_thuong_khong_bi_nham_la_loi_cuda(msg):
    assert _is_cuda_failure(Exception(msg)) is False


# ----------------------------------------------- đổi segment thành dict


class SegGia:
    def __init__(self, start, end, text, words=None, no_speech_prob=0.1, avg_logprob=-0.5):
        self.start, self.end, self.text = start, end, text
        self.words = words
        self.no_speech_prob = no_speech_prob
        self.avg_logprob = avg_logprob


class TuGia:
    def __init__(self, word, start, end):
        self.word, self.start, self.end = word, start, end


def test_doi_segment_thanh_dict_thuan():
    out = _collect([SegGia(0, 2, " xin chào ", [TuGia("xin", 0, 1), TuGia("chào", 1, 2)])])
    assert out[0]["start"] == 0.0 and out[0]["text"] == " xin chào "
    assert [w["word"] for w in out[0]["words"]] == ["xin", "chào"]


def test_bo_qua_tu_thieu_moc_gio():
    """faster-whisper đôi khi trả word không có start/end — giữ lại là vỡ khâu canh giờ."""
    words = [TuGia("tốt", 0, 1), TuGia("hỏng", None, None), TuGia(None, 1, 2)]
    assert len(_collect([SegGia(0, 2, "x", words)])[0]["words"]) == 1


def test_segment_khong_co_word_nao():
    assert _collect([SegGia(0, 2, "x", None)])[0]["words"] == []


def test_goi_callback_cho_tung_segment():
    thay = []
    _collect([SegGia(0, 1, "a"), SegGia(1, 2, "b")], on_seg=thay.append)
    assert len(thay) == 2


def test_giu_lai_diem_tin_cay_de_loc_khi_quet_bu():
    out = _collect([SegGia(0, 1, "x", no_speech_prob=0.9, avg_logprob=-2.0)])
    assert out[0]["no_speech_prob"] == 0.9
    assert out[0]["avg_logprob"] == -2.0
