"""Mẫu nhân bản ghép từ nhiều câu của đúng một nhân vật, và chỉnh độ to theo thoại gốc.

ffmpeg được thay bằng một hàm cắt thẳng từ tín hiệu tổng hợp: mỗi nhân vật là
một tần số riêng, nên nhìn phổ của mẫu là biết có lẫn giọng người khác không.
"""

from __future__ import annotations

import numpy as np
import pytest

from backend.core import dubbing
from backend.core.subtitles import Cue

TONE = {"S1": 220.0, "S2": 880.0}


def c(start, end, speaker, text="thoại"):
    return Cue(start=start, end=end, text=text, speaker=speaker)


@pytest.fixture
def phim(monkeypatch):
    """Dựng 'video' giả từ danh sách (cue, biên độ) và thay ffmpeg bằng phép cắt mảng."""
    state = {"sr": 48000, "signal": np.zeros(1, dtype=np.float32)}

    def dung(cues, seconds, amps=None):
        sr = state["sr"]
        sig = np.zeros(int(seconds * sr), dtype=np.float32)
        for i, cue in enumerate(cues):
            a, b = int(cue.start * sr), int(cue.end * sr)
            t = np.arange(b - a) / sr
            amp = (amps or {}).get(i, 0.3)
            sig[a:b] = amp * np.sin(2 * np.pi * TONE.get(cue.speaker, 440.0) * t)
        state["signal"] = sig

    def ffmpeg_gia(args, _duration, **_kw):
        args = [str(a) for a in args]
        start = float(args[args.index("-ss") + 1]) if "-ss" in args else 0.0
        length = float(args[args.index("-t") + 1]) if "-t" in args else None
        out_sr = int(args[args.index("-ar") + 1])
        sr = state["sr"]
        a = int(start * sr)
        b = len(state["signal"]) if length is None else a + int(length * sr)
        seg = state["signal"][a:b]
        idx = np.linspace(0, max(0, len(seg) - 1), int(len(seg) * out_sr / sr))
        seg = np.interp(idx, np.arange(len(seg)), seg).astype(np.float32) if len(seg) else seg
        dubbing._write_wav(args[-1], seg, out_sr)

    monkeypatch.setattr(dubbing.media, "run_ffmpeg_progress", ffmpeg_gia)
    # Không nạp mô hình véc-tơ giọng thật trong test (chậm, và tiếng sin không phải giọng người)
    monkeypatch.setattr(dubbing, "_typical_first", lambda pieces: pieces)
    return dung


def nang_luong_tan_so(path, freq):
    data, sr = dubbing._read_wav(path)
    spec = np.abs(np.fft.rfft(data))
    freqs = np.fft.rfftfreq(len(data), 1 / sr)
    band = (freqs > freq * 0.9) & (freqs < freq * 1.1)
    return float(np.square(spec[band]).sum() / np.square(spec).sum())


# ------------------------------------------------------------- mẫu ghép


def test_mau_ghep_chi_chua_giong_cua_dung_nhan_vat(phim, workdir):
    # S1 chỉ có câu ngắn 1,5 giây, xen kẽ sát với S2 — cách cắt 4 giây liền sẽ dính S2
    cues = []
    for k in range(6):
        cues.append(c(k * 3.2, k * 3.2 + 1.5, "S1"))
        cues.append(c(k * 3.2 + 1.6, k * 3.2 + 3.1, "S2"))
    phim(cues, 20)
    out = workdir / "ref.wav"
    made = dubbing.compose_reference(workdir / "v.mp4", cues, out, "S1")
    assert made is not None
    seconds, pieces = made
    assert pieces >= 2 and seconds >= dubbing.REF_MIN_TOTAL
    assert nang_luong_tan_so(out, TONE["S1"]) > 0.95
    assert nang_luong_tan_so(out, TONE["S2"]) < 0.01, "mẫu của S1 không được lẫn giọng S2"


def test_du_muc_tieu_thi_dung_va_uu_tien_cau_dai(phim, workdir):
    cues = [c(0, 1, "S1"), c(2, 8, "S1"), c(9, 13, "S1"), c(14, 15, "S1"), c(16, 17, "S1")]
    phim(cues, 18)
    seconds, pieces = dubbing.compose_reference(workdir / "v.mp4", cues, workdir / "ref.wav", "S1")
    assert pieces == 2, "câu 6 giây + câu 4 giây đã đủ 8 giây, không cần lấy thêm câu ngắn"
    assert seconds >= dubbing.REF_TARGET


def test_bo_cau_li_nhi_va_nhan_am_thanh(phim, workdir):
    cues = [c(0, 2, "S1"), c(3, 5, "S1"), c(6, 8, "S1", "[nhạc]"), c(9, 11, "S1"), c(12, 14, "S1")]
    phim(cues, 15, amps={0: 0.0003})  # câu đầu gần như im
    seconds, pieces = dubbing.compose_reference(workdir / "v.mp4", cues, workdir / "ref.wav", "S1")
    assert pieces == 3, "câu im và dòng [nhạc] không được vào mẫu"


def test_qua_it_tieng_thi_tra_none_de_roi_ve_cach_cu(phim, workdir):
    cues = [c(0, 1.0, "S1"), c(5, 5.5, "S1")]
    phim(cues, 7)
    assert dubbing.compose_reference(workdir / "v.mp4", cues, workdir / "ref.wav", "S1") is None
    assert not (workdir / "ref.wav").exists()
    assert dubbing.compose_reference(workdir / "v.mp4", cues, workdir / "ref.wav", "S9") is None


def test_extract_references_dung_mau_ghep_truoc(phim, workdir):
    cues = [c(k * 2.0, k * 2.0 + 1.6, "S1") for k in range(5)]
    phim(cues, 11)
    logs: list[str] = []
    refs, failed = dubbing.extract_references(workdir / "v.mp4", cues, workdir, on_log=logs.append)
    assert list(refs) == ["S1"] and failed == []
    assert any("ghép từ" in ln for ln in logs)


# -------------------------------------------------- độ to theo thoại gốc


def test_cau_goc_to_thi_long_to_hon_cau_goc_nho_thi_nho_hon(phim, workdir):
    cues = [c(k * 3.0, k * 3.0 + 2.0, "S1") for k in range(5)]
    phim(cues, 16, amps={0: 0.2, 1: 0.2, 2: 0.2, 3: 0.8, 4: 0.03})
    units = [{"start": x.start, "end": x.end, "speaker": "S1"} for x in cues]
    gains = dubbing.energy_gains(workdir / "vocals.wav", units, workdir)
    assert gains[0] == pytest.approx(1.0, abs=0.02)
    assert gains[3] > 1.3 and gains[4] < 0.75
    lo, hi = (10 ** (d / 20) for d in dubbing.ENERGY_RANGE_DB)
    assert all(lo - 1e-6 <= g <= hi + 1e-6 for g in gains), "không được vượt biên ±4 dB"


def test_moi_vai_so_voi_muc_thuong_cua_chinh_minh(phim, workdir):
    # S2 thu nhỏ hơn S1 nhiều nhưng nói đều -> không ai bị chỉnh
    cues = [c(k * 2.0, k * 2.0 + 1.5, "S1" if k % 2 == 0 else "S2") for k in range(8)]
    phim(cues, 17, amps={k: (0.5 if k % 2 == 0 else 0.05) for k in range(8)})
    units = [{"start": x.start, "end": x.end, "speaker": x.speaker} for x in cues]
    gains = dubbing.energy_gains(workdir / "vocals.wav", units, workdir)
    assert all(g == pytest.approx(1.0, abs=0.02) for g in gains)


def test_vai_it_cau_hoac_khung_im_thi_giu_nguyen(phim, workdir):
    cues = [c(0, 2, "S1"), c(3, 5, "S1")]
    phim(cues, 10, amps={0: 0.1, 1: 0.9})
    units = [{"start": 0, "end": 2, "speaker": "S1"}, {"start": 3, "end": 5, "speaker": "S1"},
             {"start": 6, "end": 8, "speaker": "S1"}]
    assert dubbing.energy_gains(workdir / "vocals.wav", units, workdir) == [1.0, 1.0, 1.0]


def test_khong_doc_duoc_file_thi_khong_chinh(monkeypatch, workdir):
    def hong(*a, **k):
        raise RuntimeError("ffmpeg hỏng")

    monkeypatch.setattr(dubbing.media, "run_ffmpeg_progress", hong)
    assert dubbing.energy_gains(workdir / "x.wav", [{"start": 0, "end": 1, "speaker": ""}], workdir) == [1.0]


# ------------------------------------------- chọn khúc tiêu biểu theo véc-tơ giọng


def test_khuc_lac_giong_bi_loai_va_khuc_tieu_bieu_dung_truoc(monkeypatch):
    from backend.core import voiceprint

    giong = {1.0: [1, 0, 0], 2.0: [0.98, 0.2, 0], 3.0: [0, 1, 0], 4.0: [0.95, 0.3, 0], 5.0: None}

    def vec(data, sr):
        v = giong[float(data[0])]
        return None if v is None else np.asarray(v, dtype=np.float32) / np.linalg.norm(v)

    monkeypatch.setattr(voiceprint, "available", lambda: (True, ""))
    monkeypatch.setattr(voiceprint, "embed_array", vec)
    pieces = [(t, np.full(10, t, dtype=np.float32)) for t in (1.0, 2.0, 3.0, 4.0, 5.0)]
    order = [start for start, _ in dubbing._typical_first(pieces)]
    assert 3.0 not in order, "khúc mang giọng khác hẳn phải bị loại"
    assert order[-1] == 5.0, "khúc quá ngắn để đo thì xếp cuối"
    assert set(order[:3]) == {1.0, 2.0, 4.0}


def test_khong_co_mo_hinh_giong_thi_giu_nguyen_thu_tu(monkeypatch):
    from backend.core import voiceprint

    monkeypatch.setattr(voiceprint, "available", lambda: (False, "chưa cài"))
    pieces = [(float(i), np.zeros(4, dtype=np.float32)) for i in range(4)]
    assert dubbing._typical_first(pieces) == pieces


def test_mau_ghep_khong_dai_qua_tran(phim, workdir):
    cues = [c(0, 7, "S1"), c(8, 15, "S1"), c(16, 23, "S1")]
    phim(cues, 24)
    seconds, pieces = dubbing.compose_reference(workdir / "v.mp4", cues, workdir / "ref.wav", "S1")
    assert pieces == 2 and seconds <= dubbing.REF_MAX + 0.01
