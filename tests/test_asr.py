"""Kiểm thử phần đo độ phủ của nhận dạng lời thoại.

Whisper có thể bỏ sót cả đoạn dài **mà không báo lỗi**. Mấy hàm đo dưới đây là
thứ duy nhất phát hiện ra chuyện đó, nên chúng phải đúng.
"""

from __future__ import annotations

import pytest

from backend.core.asr import (
    GAP_RESCAN,
    _collect,
    _is_cuda_failure,
    coverage,
    find_gaps,
    looks_like_speech,
    voiced_time,
)


def seg(start, end, text="chữ", **kw):
    return {"start": start, "end": end, "text": text, **kw}


def rescan_seg(text="Xin chào", no_speech=0.2, logprob=-0.5, compression=1.4):
    return {"start": 0, "end": 1, "text": text, "no_speech_prob": no_speech,
            "avg_logprob": logprob, "compression_ratio": compression}


# ------------------------------------------- giữ/bỏ đoạn quét bù


def test_giu_thoai_that_ro_rang():
    assert looks_like_speech(rescan_seg())


def test_giu_loi_hat_de_nhac_du_no_speech_cao():
    """Đo thật: lời hát "我愛你" trên nhạc to bị chấm no_speech 0,84 nhưng là tiếng thật.

    Mất đoạn này thì khán giả nghe tiếng gốc chưa dịch — đúng lỗi 'chỗ dịch chỗ mất'.
    """
    assert looks_like_speech(rescan_seg(no_speech=0.84, logprob=-1.1))


def test_bo_van_ban_lap_vi_la_whisper_bia():
    """Lời bịa trên nhạc lặp đi lặp lại nên tỉ lệ nén cao — chặn ở đây."""
    assert not looks_like_speech(rescan_seg(text="啦啦啦啦啦啦啦啦", compression=3.5))


def test_bo_doan_do_tin_qua_thap():
    assert not looks_like_speech(rescan_seg(logprob=-2.0))


@pytest.mark.parametrize("text", [
    "字幕by索兰娅",
    "請不吝點贊訂閱轉發打賞支持明鏡與點點欄目",
    "谢谢观看",
    "Subtitles by the Amara.org community",
])
def test_bo_cau_ghi_cong_va_keu_goi_dang_ky(text):
    """Whisper bịa mấy câu này trên nhạc dù độ tin cao — thoại phim không có."""
    assert not looks_like_speech(rescan_seg(text=text, no_speech=0.2, logprob=-0.3))


def test_thoai_that_khong_bi_chan_nham():
    for text in ("我愛你", "我是独眼巨人", "我们获胜了", "Tôi yêu bạn"):
        assert looks_like_speech(rescan_seg(text=text)), text


def test_bo_doan_rong():
    assert not looks_like_speech(rescan_seg(text="   "))


def test_bo_khi_gan_chac_la_khong_co_tieng():
    assert not looks_like_speech(rescan_seg(no_speech=0.95))


def test_nguong_quet_bu_bat_duoc_khoang_ngan():
    """Từng để 20s nên đoạn thoại 4–13s lọt lưới; nay phải bắt được khoảng ~4s."""
    assert GAP_RESCAN <= 4.0
    assert find_gaps([seg(0, 10), seg(14, 20)], 20) == [(10, 14)]


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


# --------------------------------- dò ngôn ngữ / câu bịa ở lượt chính (phim Thái)

from backend.core import asr  # noqa: E402


@pytest.mark.parametrize("text", ["โปรดติดตามตอนต่อไป", "โปรดติดตามต่อไป", "Thank you for watching.",
                                  "See you in the next video."])
def test_bo_cau_bia_tieng_thai_va_tieng_anh(text):
    """Đo thật (phim Thái The Rules EP5): Whisper bịa mấy câu này trên nhạc."""
    assert not looks_like_speech(rescan_seg(text=text))


def test_thoai_thai_that_khong_bi_chan():
    for text in ("วันนี้ครบสิบวันตามสัญญาแล้วนะครับ", "แม่ เป็นยังไงบ้าง"):
        assert looks_like_speech(rescan_seg(text=text)), text


def test_luot_chinh_cung_bo_cau_bia():
    notes = []
    kept = asr._drop_boilerplate([seg(0, 1, "โปรดติดตามตอนต่อไป"), seg(2, 3, "แม่")], notes)
    assert [s["text"] for s in kept] == ["แม่"]
    assert notes and "1" in notes[0]


def _wav(path, seconds):
    import wave

    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"\x00\x00" * int(seconds * 16000))
    return str(path)


class ModelDoGia:
    """Model giả: mỗi khúc trả một bảng xác suất ngôn ngữ cho sẵn."""

    def __init__(self, tables):
        self.tables, self.calls = list(tables), []

    def detect_language(self, audio=None):
        self.calls.append(len(audio))
        probs = self.tables.pop(0)
        return probs[0][0], probs[0][1], probs


def test_do_ngon_ngu_tren_khuc_co_tieng_nguoi_va_cong_xac_suat(tmp_path, monkeypatch):
    import faster_whisper.vad as vad

    # 40 s tiếng người -> 2 khúc (30 s + 10 s)
    monkeypatch.setattr(vad, "get_speech_timestamps", lambda audio, opts=None: [{"start": 0, "end": 40 * 16000}])
    model = ModelDoGia([[("th", 0.9), ("lo", 0.1)], [("th", 0.8), ("nn", 0.2)]])
    lang, prob = asr.detect_language(model, _wav(tmp_path / "a.wav", 60))
    assert lang == "th" and prob == pytest.approx(0.85)
    assert model.calls == [30 * 16000, 10 * 16000]


def test_qua_it_tieng_nguoi_thi_de_whisper_tu_do(tmp_path, monkeypatch):
    import faster_whisper.vad as vad

    monkeypatch.setattr(vad, "get_speech_timestamps", lambda audio, opts=None: [{"start": 0, "end": 16000}])
    model = ModelDoGia([])
    assert asr.detect_language(model, _wav(tmp_path / "a.wav", 10)) == (None, 0.0)
    assert model.calls == []


class InfoGia:
    def __init__(self, language="nn", duration=60.0):
        self.language, self.language_probability, self.duration = language, 0.2, duration


class WhisperGia:
    """Ghi lại ngôn ngữ mỗi lượt được giao; lượt chính có một khoảng trống dài để bị quét bù."""

    def __init__(self):
        self.langs = []

    def transcribe(self, path, **kw):
        self.langs.append(kw.get("language"))
        if kw.get("clip_timestamps"):
            return iter([SegGia(30, 31, "ขอบคุณครับ")]), InfoGia()
        segs = [SegGia(0, 2, "โปรดติดตามตอนต่อไป"), SegGia(2, 4, "แม่ เป็นยังไงบ้าง"), SegGia(50, 52, "อันนี้อากาศดีนะ")]
        return iter(segs), InfoGia()


def test_moi_luot_dung_chung_ngon_ngu_da_do(monkeypatch):
    """Trước đây lượt quét bù truyền language=None nên mỗi khúc tự dò lại trên nhạc."""
    fake = WhisperGia()
    monkeypatch.setattr(asr, "load_model", lambda *a, **k: (fake, "cpu"))
    monkeypatch.setattr(asr, "detect_language", lambda model, path: ("th", 0.98))
    logs = []
    res = asr.transcribe("khong-can-file.wav", duration=60.0, on_log=logs.append)
    assert len(fake.langs) >= 2 and set(fake.langs) == {"th"}
    assert res["language"] == "th" and res["language_probability"] == pytest.approx(0.98)
    assert "โปรดติดตามตอนต่อไป" not in [s["text"] for s in res["segments"]]
    assert any("large-v3" in m for m in logs)  # medium + tiếng Thái -> gợi ý model lớn


def test_nguoi_dung_chon_ngon_ngu_thi_khong_do_lai(monkeypatch):
    fake = WhisperGia()
    monkeypatch.setattr(asr, "load_model", lambda *a, **k: (fake, "cpu"))

    def cam_goi(*a, **k):
        raise AssertionError("không được dò khi người dùng đã chọn ngôn ngữ")

    monkeypatch.setattr(asr, "detect_language", cam_goi)
    res = asr.transcribe("x.wav", language="zh", duration=60.0)
    assert set(fake.langs) == {"zh"} and res["language"] == "zh"


def test_do_hong_thi_quay_ve_cach_cu(monkeypatch):
    fake = WhisperGia()
    monkeypatch.setattr(asr, "load_model", lambda *a, **k: (fake, "cpu"))

    def hong(*a, **k):
        raise RuntimeError("không đọc được file")

    monkeypatch.setattr(asr, "detect_language", hong)
    res = asr.transcribe("x.wav", duration=60.0)
    # lượt 1 để faster-whisper tự dò; các lượt sau dùng đúng ngôn ngữ lượt 1 báo về
    assert fake.langs[0] is None and set(fake.langs[1:]) == {"nn"}
    assert res["language"] == "nn"


class NapGia:
    """load_model giả: mỗi cỡ model một WhisperGia riêng, ghi lại lần nạp."""

    def __init__(self, device="cuda", hong=()):
        self.device, self.hong, self.models, self.calls = device, set(hong), {}, []

    def __call__(self, size="medium", device="auto", on_log=None, cpu_fallback=True):
        self.calls.append((size, device, cpu_fallback))
        if size in self.hong:
            raise RuntimeError("CUDA out of memory")
        return self.models.setdefault(size, WhisperGia()), self.device


def _tu_doi(monkeypatch, lang="th", device="cuda", co_san=True, hong=()):
    nap = NapGia(device, hong)
    monkeypatch.setattr(asr, "load_model", nap)
    monkeypatch.setattr(asr, "detect_language", lambda model, path: (lang, 0.98))
    monkeypatch.setattr(asr, "_model_on_disk", lambda size: co_san)
    logs = []
    res = asr.transcribe("x.wav", duration=60.0, on_log=logs.append)
    return nap, res, logs


def test_tieng_thai_tren_gpu_tu_doi_sang_large_v3(monkeypatch):
    monkeypatch.setitem(asr._cache, ("medium", "cuda", "float16"), object())
    nap, res, logs = _tu_doi(monkeypatch)
    assert ("large-v3", "cuda", False) in nap.calls  # không lặng lẽ rơi về CPU
    # dò ngôn ngữ bằng medium, mọi lượt nghe bằng large-v3
    assert nap.models["medium"].langs == [] and set(nap.models["large-v3"].langs) == {"th"}
    assert res["model"] == "large-v3"
    assert any("tự chuyển sang Whisper `large-v3`" in m for m in logs)
    assert not any(m.startswith("Gợi ý") for m in logs)
    assert ("medium", "cuda", "float16") not in asr._cache  # nhả VRAM của medium


def test_tieng_trung_giu_medium(monkeypatch):
    nap, res, logs = _tu_doi(monkeypatch, lang="zh")
    assert [c[0] for c in nap.calls] == ["medium"] and res["model"] == "medium"
    assert not any("large-v3" in m for m in logs)


@pytest.mark.parametrize("kw, ly_do", [
    ({"device": "cpu"}, "CPU"),
    ({"co_san": False}, "chưa có model"),
    ({"hong": ("large-v3",)}, "Không nạp được"),
])
def test_khong_doi_duoc_thi_giu_medium_va_noi_vi_sao(monkeypatch, kw, ly_do):
    nap, res, logs = _tu_doi(monkeypatch, **kw)
    assert res["model"] == "medium" and set(nap.models["medium"].langs) == {"th"}
    goi_y = [m for m in logs if m.startswith("Gợi ý")]
    assert len(goi_y) == 1 and ly_do in goi_y[0]


def test_tat_tu_doi_hoac_tu_chon_model_khac(monkeypatch):
    monkeypatch.setattr(asr, "AUTO_UPGRADE", False)
    nap, res, _ = _tu_doi(monkeypatch)
    assert res["model"] == "medium" and [c[0] for c in nap.calls] == ["medium"]

    monkeypatch.setattr(asr, "AUTO_UPGRADE", True)
    nap = NapGia()
    monkeypatch.setattr(asr, "load_model", nap)
    res = asr.transcribe("x.wav", model_size="small", duration=60.0)
    assert res["model"] == "small" and [c[0] for c in nap.calls] == ["small"]
