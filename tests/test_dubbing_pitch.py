"""Tone giọng lồng theo thoại gốc: đo cao độ đích của từng vai, tính mức chỉnh, và dịch cao độ thật.

Giọng người được thay bằng sóng có hoạ âm ở một tần số cơ bản biết trước, nên đo
lại F0 sau khi chỉnh là biết có về đúng đích không.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from backend.core import dubbing


def giong(hz: float, seconds: float, sr: int = dubbing.SR, amp: float = 0.3) -> np.ndarray:
    t = np.arange(int(seconds * sr)) / sr
    x = sum(np.sin(2 * np.pi * hz * k * t) / k for k in (1, 2, 3))
    return (amp * x / 1.8).astype(np.float32)


@pytest.fixture
def workdir(tmp_path):
    return tmp_path


@pytest.fixture
def goc(monkeypatch, workdir):
    """Dựng file 'giọng gốc' từ danh sách (start, end, speaker, Hz) và thay bước ffmpeg đổi tần số lấy mẫu."""
    state = {"signal": np.zeros(1, dtype=np.float32)}

    def dung(rows, seconds):
        sig = np.zeros(int(seconds * dubbing.SR), dtype=np.float32)
        for start, end, _spk, hz in rows:
            a = int(start * dubbing.SR)
            seg = giong(hz, end - start) if hz else np.zeros(int((end - start) * dubbing.SR), dtype=np.float32)
            sig[a:a + seg.size] = seg
        state["signal"] = sig
        return [{"start": s, "end": e, "speaker": spk} for s, e, spk, _ in rows]

    def ffmpeg_gia(args, _duration, **_kw):
        args = [str(a) for a in args]
        out_sr = int(args[args.index("-ar") + 1])
        step = dubbing.SR // out_sr
        dubbing._write_wav(args[-1], state["signal"][::step], out_sr)

    monkeypatch.setattr(dubbing.media, "run_ffmpeg_progress", ffmpeg_gia)
    return dung


def nua_cung(a: float, b: float) -> float:
    return 12 * math.log2(a / b)


# ------------------------------------------------------------ cao độ đích


def test_moi_vai_co_tam_giong_rieng(goc, workdir):
    rows = [(k * 2.0, k * 2.0 + 1.5, "S1" if k % 2 == 0 else "S2", 120.0 if k % 2 == 0 else 220.0) for k in range(8)]
    units = goc(rows, 17)
    targets = dubbing.pitch_targets(workdir / "vocals.wav", units, workdir)
    for u, t in zip(units, targets):
        assert t == pytest.approx(120.0 if u["speaker"] == "S1" else 220.0, rel=0.02)


def test_cau_len_giong_thi_dich_nhich_theo_mot_nua_va_co_chan(goc, workdir):
    # bốn câu ở tầm thường 150 Hz, một câu lên 4 nửa cung, một câu vọt hẳn một quãng tám
    cao = 150.0 * 2 ** (4 / 12)
    rows = [(k * 2.0, k * 2.0 + 1.5, "S1", 150.0) for k in range(4)] + [(8, 9.5, "S1", cao), (10, 11.5, "S1", 300.0)]
    targets = dubbing.pitch_targets(workdir / "vocals.wav", goc(rows, 13), workdir)
    assert targets[0] == pytest.approx(150.0, rel=0.02)
    assert nua_cung(targets[4], 150.0) == pytest.approx(4 * dubbing.PITCH_FOLLOW, abs=0.3)
    assert nua_cung(targets[5], 150.0) == pytest.approx(dubbing.PITCH_FOLLOW_RANGE[1], abs=0.3)


def test_cau_khong_do_duoc_lay_tam_cua_vai_con_vai_it_cau_thi_khong_chinh(goc, workdir):
    rows = [(k * 2.0, k * 2.0 + 1.5, "S1", 180.0) for k in range(3)] + [(6, 7.5, "S1", 0.0), (8, 9.5, "S2", 110.0)]
    targets = dubbing.pitch_targets(workdir / "vocals.wav", goc(rows, 11), workdir)
    assert targets[3] == pytest.approx(180.0, rel=0.02), "câu im lấy tầm thường của vai"
    assert targets[4] == 0.0, "vai chỉ có một câu thì không đủ căn cứ"


def test_khong_doc_duoc_file_thi_khong_chinh(monkeypatch, workdir):
    def hong(*a, **k):
        raise RuntimeError("ffmpeg hỏng")

    monkeypatch.setattr(dubbing.media, "run_ffmpeg_progress", hong)
    assert dubbing.pitch_targets(workdir / "x.wav", [{"start": 0, "end": 1, "speaker": ""}], workdir) == [0.0]


# ------------------------------------------------------------ mức chỉnh


def test_muc_chinh_dung_huong_va_bi_chan():
    doc = giong(200.0, 2.0)
    assert dubbing.pitch_correction(doc, 200.0 * 2 ** (-2 / 12)) == pytest.approx(-2.0, abs=0.25)
    assert dubbing.pitch_correction(doc, 200.0 * 2 ** (5 / 12)) == dubbing.PITCH_MAX_SHIFT
    assert dubbing.pitch_correction(doc, 203.0) == 0.0, "lệch dưới nửa nửa-cung thì để yên"
    assert dubbing.pitch_correction(doc, 100.0) == 0.0, "lệch cả quãng tám là đo nhầm, không chỉnh"
    assert dubbing.pitch_correction(doc, 0.0) == 0.0
    assert dubbing.pitch_correction(np.zeros(dubbing.SR, dtype=np.float32), 150.0) == 0.0


# ------------------------------------------------------------ dịch cao độ thật (ffmpeg)


@pytest.mark.parametrize("co_rubberband", [True, False])
def test_dich_cao_do_ve_dung_dich_va_giu_do_dai(workdir, monkeypatch, co_rubberband):
    try:
        dubbing.media.ffmpeg_exe()
    except Exception:
        pytest.skip("không có ffmpeg")
    if co_rubberband and not dubbing._has_filter("rubberband"):
        pytest.skip("ffmpeg này không có rubberband")
    if not co_rubberband:
        monkeypatch.setattr(dubbing, "_has_filter", lambda name: False)
    doc = giong(200.0, 2.0)
    ra = dubbing._pitch_shift(doc, -2.0, workdir, "t")
    assert abs(ra.size - doc.size) / doc.size < 0.03, "độ dài câu không được đổi"
    sau = dubbing._median_f0(ra[::3], dubbing.SR // 3)
    assert nua_cung(sau, 200.0) == pytest.approx(-2.0, abs=0.3)
    assert not list(workdir.glob("*.wav")), "không để lại file tạm"


# ------------------------------------------------------------ chọn khúc ghép mẫu theo cao độ


def khuc(hz: float, seconds: float = 1.5):
    return (0.0, giong(hz, seconds, sr=dubbing.REF_SR))


def test_mau_ghep_chi_lay_cau_tu_tam_giong_tro_len():
    pieces = [khuc(hz) for hz in (150.0, 170.0, 200.0, 220.0, 240.0)]
    kept = dubbing._upper_pitch(pieces)
    got = sorted(round(dubbing._median_f0(dubbing._to_pitch_sr(d, dubbing.REF_SR), dubbing.PITCH_SR)) for _s, d in kept)
    assert got == pytest.approx([200, 220, 240], abs=2), "hai câu trầm hơn tầm giọng (200 Hz) phải bị loại"


def test_cac_cau_cung_cao_do_thi_giu_het():
    pieces = [khuc(180.0) for _ in range(4)]
    assert len(dubbing._upper_pitch(pieces)) == 4


def test_loc_xong_khong_du_giay_thi_tra_lai_nguyen_danh_sach():
    # nửa trên chỉ còn 2 khúc × 1 giây < REF_MIN_TOTAL
    pieces = [khuc(150.0, 3.0), khuc(160.0, 3.0), khuc(200.0, 1.0), khuc(230.0, 1.0)]
    assert dubbing._upper_pitch(pieces) == pieces


def test_it_khuc_hoac_khong_do_duoc_cao_do_thi_giu_nguyen():
    it = [khuc(150.0), khuc(250.0)]
    assert dubbing._upper_pitch(it) == it
    im = [(0.0, np.zeros(dubbing.REF_SR, dtype=np.float32)) for _ in range(4)]
    assert dubbing._upper_pitch(im) == im


# ------------------------------------------------------------ cảnh báo vai nhân bản lệch tone


def test_bao_cao_chi_neu_vai_lech_tu_bon_nua_cung_va_du_cau():
    gaps = {
        "S1": [7.0, 8.0, 6.5],      # bản đọc trầm hơn gốc ~7 nửa cung
        "S2": [1.0, -0.5, 2.0],     # lệch ít -> không báo
        "S3": [9.0, 9.0],           # mới hai câu -> chưa đủ căn cứ
        "S4": [-5.0, -4.5, -6.0],   # bản đọc CAO hơn gốc
    }
    assert dubbing.clone_pitch_report(gaps) == {"S1": -7.0, "S4": 5.0}


class GiongTram:
    """TTS giả: vai nào cũng đọc ra 120 Hz."""

    def infer(self, text, **kw):
        return giong(120.0, 1.2)


def test_long_tieng_bao_vai_nhan_ban_tram_han_so_voi_goc(goc, workdir, monkeypatch):
    from backend.core.subtitles import Cue

    monkeypatch.setattr(dubbing, "get_engine", lambda: GiongTram())
    rows = [(k * 3.0, k * 3.0 + 2.0, "S1", 200.0) for k in range(4)]
    goc(rows, 13)
    cues = [Cue(start=s, end=e, text="x", text2="Xin chào anh.", speaker=spk) for s, e, spk, _ in rows]
    logs: list[str] = []
    _, stats = dubbing.build_dub_track(
        cues, 13.0, workdir, ref_map={"S1": "mau.wav"}, per_cue=True, on_log=logs.append,
        pitch_from=workdir / "vocals.wav", pitch_shift=False,
    )
    assert stats["pitch_off"] == {"S1": pytest.approx(-8.8, abs=0.3)}
    assert stats["pitch_matched"] == 0, "chỉ đo, không chỉnh"
    assert any("Vai S1" in ln and "trầm hơn giọng gốc" in ln for ln in logs)


def test_giong_dung_san_thi_khong_do_khong_bao(goc, workdir, monkeypatch):
    from backend.core.subtitles import Cue

    monkeypatch.setattr(dubbing, "get_engine", lambda: GiongTram())
    rows = [(k * 3.0, k * 3.0 + 2.0, "S1", 200.0) for k in range(4)]
    goc(rows, 13)
    cues = [Cue(start=s, end=e, text="x", text2="Xin chào anh.", speaker=spk) for s, e, spk, _ in rows]
    _, stats = dubbing.build_dub_track(
        cues, 13.0, workdir, voice="A", per_cue=True, pitch_from=workdir / "vocals.wav", pitch_shift=False,
    )
    assert "pitch_off" not in stats
