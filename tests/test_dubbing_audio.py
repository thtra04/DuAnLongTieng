"""Kiểm thử phần xử lý âm thanh của lồng tiếng: ép thời gian, cắt lặng, cân âm lượng.

Không chạy ffmpeg và không gọi TTS — chỉ kiểm các hàm tính toán thuần và phần
đọc/ghi wav.
"""

from __future__ import annotations

import math
import re

import numpy as np
import pytest

from backend.core import dubbing
from backend.core.dubbing import (
    GAIN_LIMIT_DB,
    SR,
    VOICE_ABOVE_BG_DB,
    VOICE_ABOVE_GAP_DB,
    VOICE_TARGET_DBFS,
    _atempo_chain,
    _cap_unit,
    _clean_for_tts,
    _db,
    _read_wav,
    _runaway,
    _trim_silence,
    _write_wav,
    balance,
    untranslated_lines,
    wav_levels,
)
from backend.core.subtitles import Cue


# --------------------------------------------------- chuỗi atempo


def tich_atempo(chain: str) -> float:
    return math.prod(float(x) for x in re.findall(r"atempo=([\d.]+)", chain))


@pytest.mark.parametrize("factor", [0.25, 0.5, 0.9, 1.0, 1.5, 2.0, 3.0, 5.0, 8.0])
def test_chuoi_atempo_nhan_lai_dung_he_so(factor):
    """ffmpeg chỉ nhận 0,5–2,0 mỗi tầng nên phải nối tầng — tích phải đúng hệ số gốc."""
    assert tich_atempo(_atempo_chain(factor)) == pytest.approx(factor, rel=1e-4)


@pytest.mark.parametrize("factor", [0.25, 0.5, 1.5, 3.0, 8.0])
def test_moi_tang_atempo_nam_trong_khoang_ffmpeg_cho_phep(factor):
    for value in re.findall(r"atempo=([\d.]+)", _atempo_chain(factor)):
        assert 0.5 <= float(value) <= 2.0


def test_he_so_lon_can_nhieu_tang():
    assert _atempo_chain(1.5).count("atempo") == 1
    assert _atempo_chain(5.0).count("atempo") >= 3


# ------------------------------------------------------- cắt lặng


def am_thanh(giay_lang_dau: float, giay_tieng: float, giay_lang_cuoi: float):
    rng = np.random.default_rng(0)
    tieng = (rng.random(int(giay_tieng * SR), dtype=np.float32) - 0.5) * 0.8
    return np.concatenate([
        np.zeros(int(giay_lang_dau * SR), dtype=np.float32),
        tieng,
        np.zeros(int(giay_lang_cuoi * SR), dtype=np.float32),
    ])


def test_cat_lang_dau_va_cuoi():
    """VieNeu chèn ~100ms lặng đầu và ~140ms cuối; không cắt là mọi câu vào trễ."""
    goc = am_thanh(0.3, 1.0, 0.3)
    cat, da_cat = _trim_silence(goc)
    assert cat.size < goc.size
    assert da_cat == pytest.approx(0.6, abs=0.1)


def test_giu_lai_mot_chut_de_khong_cut_phu_am():
    goc = am_thanh(0.5, 1.0, 0.5)
    cat, _ = _trim_silence(goc, keep=0.02)
    # phần tiếng là 1,0s; giữ thêm 0,02s mỗi đầu
    assert cat.size / SR == pytest.approx(1.04, abs=0.02)


def test_khong_co_lang_thi_khong_cat_gi():
    goc = am_thanh(0, 1.0, 0)
    _, da_cat = _trim_silence(goc)
    assert da_cat == 0.0


def test_toan_lang_thi_tra_nguyen():
    goc = np.zeros(SR, dtype=np.float32)
    cat, da_cat = _trim_silence(goc)
    assert da_cat == 0.0 and cat.size == goc.size


def test_am_thanh_rong():
    cat, da_cat = _trim_silence(np.zeros(0, dtype=np.float32))
    assert da_cat == 0.0 and cat.size == 0


# ------------------------------------------------ phát hiện sinh chạy loạn


def test_clip_dai_bat_thuong_bi_bat():
    """TTS đôi khi không gặp điểm kết và sinh tới trần 24 giây."""
    assert _runaway(24.0, "Dạ.") is True


@pytest.mark.parametrize("text,giay", [("Dạ.", 0.64), ("Cứu tôi!", 1.28), ("Xin chào các bạn.", 2.0)])
def test_cau_ngan_that_khong_bi_bat_oan(text, giay):
    assert _runaway(giay, text) is False


def test_cau_dai_duoc_phep_doc_lau_hon():
    assert _runaway(8.0, "x" * 200) is False


# ---------------------------------------------------- làm sạch chữ


def test_bo_xuong_dong_va_the_html():
    assert _clean_for_tts("dòng một\ndòng hai <i>nghiêng</i>") == "dòng một dòng hai nghiêng."


def test_them_dau_cham_khi_thieu():
    assert _clean_for_tts("xin chào") == "xin chào."


def test_khong_them_khi_da_co_dau_cau():
    assert _clean_for_tts("xin chào!") == "xin chào!"


def test_manh_giua_cau_khong_bi_cham_cau():
    """Chấm câu vào từng mảnh trước khi nối làm TTS tụt giọng giữa câu."""
    assert _clean_for_tts("Hôm nay", add_stop=False) == "Hôm nay"


def test_khong_co_gi_doc_duoc_tra_rong():
    assert _clean_for_tts("...") == ""
    assert _clean_for_tts("♪♪♪") == ""
    assert _clean_for_tts("第一集") == ""


def test_chu_viet_thuong_van_doc_duoc():
    assert _clean_for_tts("Ừ") != ""
    assert _clean_for_tts("123") != ""


# ------------------------------------- bản dịch còn sót chữ tiếng gốc


def test_bo_chu_han_con_sot_trong_dong_nua_viet_nua_trung():
    """Engine dịch trả nguyên văn đoạn nó chịu thua -> dòng nửa Việt nửa Trung.

    Để nguyên thì giọng tiếng Việt đọc sai hoặc chạy loạn; phải bỏ phần chữ Hán
    mà vẫn giữ đủ phần tiếng Việt.
    """
    out = _clean_for_tts("我們獲勝了只顧哔哔哔Công ty có thể cung cấp")
    assert out == "Công ty có thể cung cấp."


def test_giu_nguyen_dau_tieng_viet():
    assert _clean_for_tts("Đường phố Hà Nội rất đẹp") == "Đường phố Hà Nội rất đẹp."


@pytest.mark.parametrize("raw", ["こんにちは", "안녕하세요", "第一集"])
def test_dong_toan_chu_tieng_goc_thi_rong(raw):
    assert _clean_for_tts(raw) == ""


def test_ke_ten_dong_dich_do_dang():
    """Phải gọi tên dòng nào còn chữ tiếng gốc — im lặng bỏ là 'chỗ dịch chỗ mất'."""
    cues = [
        Cue(0, 1, "a", "Xin chào"),
        Cue(1, 2, "b", "我們獲勝了Công ty"),
        Cue(2, 3, "c", "我是獨眼巨人"),
    ]
    assert untranslated_lines(cues) == [2, 3]


def test_khong_bao_nham_khi_dich_sach():
    cues = [Cue(0, 1, "a", "Xin chào"), Cue(1, 2, "b", "Tạm biệt nhé")]
    assert untranslated_lines(cues) == []


# ------------------------------------------- chẻ đơn vị đọc quá dài


def cue(start, end, text="chữ"):
    return Cue(start=start, end=end, text=text, text2=text)


def test_don_vi_ngan_khong_bi_che():
    cues = [cue(0, 1), cue(1, 2)]
    assert _cap_unit(cues, [0, 1]) == [[0, 1]]


def test_don_vi_qua_dai_bi_che_o_khoang_lang_to_nhat():
    # khoảng lặng lớn nhất nằm giữa cue 1 và 2
    cues = [cue(0, 5), cue(5.1, 10), cue(20, 25), cue(25.1, 40)]
    assert _cap_unit(cues, [0, 1, 2, 3]) == [[0, 1], [2, 3]]


def test_mot_cue_thi_khong_che_duoc():
    assert _cap_unit([cue(0, 100)], [0]) == [[0]]


def test_che_khong_lam_mat_cue_nao():
    cues = [cue(i * 4, i * 4 + 3.5, "x" * 60) for i in range(12)]
    phang = [i for g in _cap_unit(cues, list(range(12))) for i in g]
    assert phang == list(range(12))


# --------------------------------------------------- đọc/ghi wav


def test_ghi_roi_doc_lai_wav(workdir):
    goc = (np.sin(np.linspace(0, 100, SR)) * 0.5).astype(np.float32)
    path = _write_wav(workdir / "t.wav", goc)
    lai, sr = _read_wav(path)

    assert sr == SR
    assert lai.size == goc.size
    assert np.max(np.abs(lai - goc)) < 0.001, "sai số quá lớn khi qua int16"


def test_wav_bi_kep_bien_do(workdir):
    """Biên độ vượt 1.0 phải bị kẹp, nếu không int16 tràn số thành tiếng rè."""
    path = _write_wav(workdir / "to.wav", np.array([5.0, -5.0], dtype=np.float32))
    lai, _ = _read_wav(path)
    assert np.max(np.abs(lai)) <= 1.001


def test_do_muc_wav(workdir):
    to = _write_wav(workdir / "to.wav", np.full(SR, 0.5, dtype=np.float32))
    nho = _write_wav(workdir / "nho.wav", np.full(SR, 0.05, dtype=np.float32))

    muc_to, dinh_to = wav_levels(to)
    muc_nho, _ = wav_levels(nho)
    assert muc_to > muc_nho
    assert dinh_to == pytest.approx(_db(0.5), abs=0.5)


def test_do_muc_bo_qua_khoang_lang(workdir):
    """Track lồng tiếng im 80–90% thời lượng; lấy RMS cả file sẽ ra số vô nghĩa."""
    data = np.concatenate([
        np.full(SR, 0.5, dtype=np.float32),
        np.zeros(SR * 9, dtype=np.float32),
    ])
    muc, _ = wav_levels(_write_wav(workdir / "thua.wav", data))
    assert muc == pytest.approx(_db(0.5), abs=1.0), "phải đo phần có tiếng, không phải cả file"


def test_wav_im_lang_tra_muc_rat_thap(workdir):
    muc, dinh = wav_levels(_write_wav(workdir / "im.wav", np.zeros(SR, dtype=np.float32)))
    assert muc <= -90 and dinh <= -90


# ------------------------------------------------- cân âm lượng


@pytest.fixture
def giong_yeu(workdir):
    """Track giọng đọc ~-26 dBFS — thấp hơn mức mong muốn nên phải được kéo lên."""
    return _write_wav(workdir / "dub.wav", np.full(SR, 0.05, dtype=np.float32))


def test_keo_giong_len_muc_mong_muon(giong_yeu, workdir, monkeypatch):
    monkeypatch.setattr(dubbing, "original_level", lambda *a, **k: -12.0)
    dub_vol, _, _ = balance(giong_yeu, workdir / "phim.mp4", 0.45, tmpdir=workdir)

    muc_goc, _ = wav_levels(giong_yeu)
    assert _db(dub_vol) == pytest.approx(VOICE_TARGET_DBFS - muc_goc, abs=0.5)


def test_khong_keo_qua_gioi_han(workdir, monkeypatch):
    monkeypatch.setattr(dubbing, "original_level", lambda *a, **k: -12.0)
    rat_yeu = _write_wav(workdir / "d.wav", np.full(SR, 0.001, dtype=np.float32))
    dub_vol, _, _ = balance(rat_yeu, workdir / "phim.mp4", 0.45, tmpdir=workdir)
    assert _db(dub_vol) <= GAIN_LIMIT_DB[1] + 0.01


def test_khong_dung_dinh_lam_tran_gain(workdir, monkeypatch):
    """build_dub_track ghim đỉnh về 0.99; lấy đỉnh làm trần thì gain luôn ra 0 dB."""
    monkeypatch.setattr(dubbing, "original_level", lambda *a, **k: -12.0)
    data = np.full(SR, 0.03, dtype=np.float32)
    data[0] = 0.99  # một đỉnh đơn độc sát trần
    path = _write_wav(workdir / "d.wav", data)

    dub_vol, _, _ = balance(path, workdir / "phim.mp4", 0.45, tmpdir=workdir)
    assert dub_vol > 1.5, "đỉnh không được phép chặn mức kéo"


def test_ducking_ha_nen_thap_hon_giong(giong_yeu, workdir, monkeypatch):
    monkeypatch.setattr(dubbing, "original_level", lambda *a, **k: -10.0)
    dub_vol, bg_vol, duck_db = balance(
        giong_yeu, workdir / "phim.mp4", 0.45, duck=True, tmpdir=workdir
    )
    muc_goc, _ = wav_levels(giong_yeu)
    giong_sau = muc_goc + _db(dub_vol)
    nen_luc_nghi = -10.0 + _db(bg_vol)

    assert giong_sau - nen_luc_nghi >= VOICE_ABOVE_GAP_DB - 0.5
    assert duck_db == pytest.approx(VOICE_ABOVE_BG_DB - VOICE_ABOVE_GAP_DB)


def test_khong_bao_gio_tu_nang_nen_qua_muc_nguoi_dung_dat(giong_yeu, workdir, monkeypatch):
    """`original_volume` là TRẦN người dùng đặt — tool chỉ được hạ, không được nâng."""
    monkeypatch.setattr(dubbing, "original_level", lambda *a, **k: -40.0)
    _, bg_vol, _ = balance(giong_yeu, workdir / "phim.mp4", 0.20, duck=True, tmpdir=workdir)
    assert bg_vol <= 0.20 + 1e-6


def test_bo_tieng_goc_thi_nen_ve_khong(giong_yeu, workdir):
    _, bg_vol, duck_db = balance(
        giong_yeu, workdir / "phim.mp4", 0.45, keep_original=False, tmpdir=workdir
    )
    assert bg_vol == 0.0 and duck_db == 0.0


def test_khong_do_duoc_tieng_goc_thi_giu_nguyen_muc_nguoi_dung(giong_yeu, workdir, monkeypatch):
    monkeypatch.setattr(dubbing, "original_level", lambda *a, **k: None)
    _, bg_vol, duck_db = balance(giong_yeu, workdir / "phim.mp4", 0.33, tmpdir=workdir)
    assert bg_vol == 0.33 and duck_db == 0.0


def test_track_im_lang_thi_bo_qua_can_am_luong(workdir):
    im = _write_wav(workdir / "im.wav", np.zeros(SR, dtype=np.float32))
    dub_vol, bg_vol, duck_db = balance(im, workdir / "phim.mp4", 0.45, boost=1.0, tmpdir=workdir)
    assert (dub_vol, bg_vol, duck_db) == (1.0, 0.45, 0.0)
