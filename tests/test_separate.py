"""Kiểm thử bỏ giọng gốc (separate.py), trộn với nền đã tách (mux_dub bg_wav) và đọc lại câu TTS chạy loạn."""

from __future__ import annotations

import wave
from pathlib import Path

import numpy as np
import pytest

from backend.core import dubbing, separate
from backend.core.subtitles import Cue


def _wav(path: Path, seconds: float = 1.0, sr: int = 48000, freq: float = 220.0, amp: float = 0.3) -> Path:
    t = np.arange(int(seconds * sr)) / sr
    x = (np.sin(2 * np.pi * freq * t) * amp * 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr); w.writeframes(x.tobytes())
    return path


# ------------------------------------------------------------------ separate


def test_available_bao_thieu_thu_vien(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def fake(name, *a, **k):
        if name.startswith("demucs"):
            raise ImportError("no demucs")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", fake)
    ok, why = separate.available()
    assert ok is False and "separate" in why


def test_split_vocals_dung_lai_ket_qua_cu(tmp_path):
    """Đã có vocals.wav + no_vocals.wav thì không chạy Demucs nữa (16 phút tách mất ~14 phút)."""
    v, r = _wav(tmp_path / "vocals.wav"), _wav(tmp_path / "no_vocals.wav")
    logs = []
    out = separate.split_vocals(tmp_path / "khong_ton_tai.mp4", tmp_path, on_log=logs.append)
    assert out == (v, r)
    assert any("lần trước" in m for m in logs)


def test_split_vocals_goi_demucs_va_ghi_hai_file(tmp_path, monkeypatch):
    """Giả lập Separator: vocals = nửa tín hiệu, nền = phần còn lại; kiểm tra file ra và tiến độ."""
    import sys
    import types

    src = _wav(tmp_path / "mix.wav", seconds=2.0)
    calls = {}

    class FakeSep:
        samplerate = 44100

        def __init__(self, **kw):
            calls["kw"] = kw

        def separate_audio_file(self, path):
            import torch

            calls["path"] = Path(path)
            cb = calls["kw"]["callback"]
            cb({"state": "end", "audio_length": 100, "segment_offset": 0, "segment_length": 50})
            cb({"state": "end", "audio_length": 100, "segment_offset": 50, "segment_length": 50})
            origin = torch.ones(2, 4410) * 0.5
            return origin, {"vocals": origin * 0.4}

    def fake_save(wav, path, samplerate, **kw):
        arr = wav.numpy() if hasattr(wav, "numpy") else np.asarray(wav)
        _wav(Path(path), seconds=arr.shape[-1] / samplerate, sr=samplerate, amp=float(abs(arr).max()))

    fake_api = types.SimpleNamespace(Separator=FakeSep, save_audio=fake_save)
    monkeypatch.setitem(sys.modules, "demucs", types.SimpleNamespace(api=fake_api))
    monkeypatch.setitem(sys.modules, "demucs.api", fake_api)
    monkeypatch.setattr(separate, "_extract_stereo", lambda video, out: _wav(out, seconds=0.1, sr=44100))
    pytest.importorskip("torch")

    progress = []
    vocals, rest = separate.split_vocals(src, tmp_path, on_progress=progress.append)
    assert vocals.exists() and rest.exists()
    assert calls["kw"]["model"] == separate.MODEL and calls["kw"]["device"] == "cpu"
    assert progress[-1] == 1.0 and 0.4 < progress[0] < 0.6
    assert not (tmp_path / "mix44.wav").exists()          # file tạm đã dọn


# ------------------------------------------------------------ mux với nền tách


def test_mux_dub_dung_nen_da_tach_lam_dau_vao_thu_ba(tmp_path, monkeypatch):
    bg = _wav(tmp_path / "no_vocals.wav")
    dub = _wav(tmp_path / "dub.wav")
    seen = {}
    monkeypatch.setattr(dubbing.media, "run_ffmpeg_progress", lambda args, *a, **k: seen.setdefault("args", args))
    monkeypatch.setattr(dubbing.media, "probe", lambda v: (_ for _ in ()).throw(AssertionError("không được probe")))
    dubbing.mux_dub(tmp_path / "phim.mp4", dub, tmp_path / "ra.mp4", original_volume=1.0, keep_original=True,
                    duck=False, bg_wav=bg)
    args = seen["args"]
    assert args[:6] == ["-i", str((tmp_path / "phim.mp4").resolve()), "-i", str(dub.resolve()), "-i", str(bg.resolve())]
    filt = args[args.index("-filter_complex") + 1]
    assert "[2:a]volume=1.0000" in filt and "[0:a]" not in filt


def test_mux_dub_khong_bg_wav_van_nhu_cu(tmp_path, monkeypatch):
    dub = _wav(tmp_path / "dub.wav")
    seen = {}
    monkeypatch.setattr(dubbing.media, "run_ffmpeg_progress", lambda args, *a, **k: seen.setdefault("args", args))
    monkeypatch.setattr(dubbing.media, "probe", lambda v: {"has_audio": True})
    dubbing.mux_dub(tmp_path / "phim.mp4", dub, tmp_path / "ra.mp4", original_volume=0.4, keep_original=True, duck=False)
    filt = seen["args"][seen["args"].index("-filter_complex") + 1]
    assert "[0:a]volume=0.4000" in filt and "[2:a]" not in filt


def test_duck_filter_nhan_nhan_dau_vao_nen():
    f = dubbing._duck_filter(0.5, 6.0, -18.0, 1.0, "[2:a]")
    assert "[2:a]volume=0.5000" in f and "sidechaincompress" in f


# ------------------------------------------------------- TTS đọc lại khi chạy loạn


class _Engine:
    """Lần đầu sinh 24 s (chạy loạn), lần sau sinh bình thường."""

    def __init__(self, bad_first: int):
        self.bad_first, self.calls = bad_first, 0

    def infer(self, text, **kw):
        self.calls += 1
        n = int((24.0 if self.calls <= self.bad_first else 0.8) * dubbing.SR)
        return np.full(n, 0.2, dtype=np.float32)


def test_build_dub_track_doc_lai_cau_chay_loan(tmp_path, monkeypatch):
    eng = _Engine(bad_first=1)
    monkeypatch.setattr(dubbing, "get_engine", lambda: eng)
    monkeypatch.setattr(dubbing, "_time_stretch", lambda a, f, d, t: a)
    cues = [Cue(start=0.0, end=1.5, text="x", text2="Xin chào các bạn.")]
    logs = []
    _, stats = dubbing.build_dub_track(cues, 3.0, tmp_path, voice="A", on_log=logs.append)
    assert stats["count"] == 1 and stats["failed"] == 0 and stats["runaway"] == 0
    assert eng.calls == 2 and any("đọc lại" in m for m in logs)


def test_build_dub_track_bo_cau_khi_doc_lai_van_loan(tmp_path, monkeypatch):
    eng = _Engine(bad_first=99)
    monkeypatch.setattr(dubbing, "get_engine", lambda: eng)
    cues = [Cue(start=0.0, end=1.5, text="x", text2="Xin chào các bạn.")]
    # đọc lại đủ số lần mà vẫn loạn -> bỏ câu; câu duy nhất bị bỏ thì báo lỗi không đọc được câu nào
    with pytest.raises(dubbing.DubError):
        dubbing.build_dub_track(cues, 4.0, tmp_path, voice="A")
    assert eng.calls == dubbing.RUNAWAY_RETRIES + 1


# ------------------------------------------------------------ dùng lại kết quả tách


def test_split_vocals_chep_tu_thu_muc_du_an_phan_tich(tmp_path):
    src_dir = tmp_path / "phan_tich"
    src_dir.mkdir()
    _wav(src_dir / "vocals.wav"), _wav(src_dir / "no_vocals.wav")
    work = tmp_path / "xuat"
    work.mkdir()
    logs = []
    v, r = separate.split_vocals(tmp_path / "x.mp4", work, on_log=logs.append, reuse_from=[tmp_path / "khong_co", src_dir])
    assert v == work / "vocals.wav" and r == work / "no_vocals.wav" and v.exists() and r.exists()
    assert any("lúc phân tích" in m for m in logs)


def test_analyze_steps_co_buoc_tach_khi_bat_tuy_chon():
    from backend.core.pipeline import analyze_steps

    base = {"source_type": "file", "sub_mode": "auto", "gender_split": True}
    assert "separate" not in [s.key for s in analyze_steps(base)]
    keys = [s.key for s in analyze_steps({**base, "separate_first": True})]
    assert keys.index("separate") < keys.index("gender")
    # không đo giọng thì tách cũng vô ích -> không thêm bước
    assert "separate" not in [s.key for s in analyze_steps({"source_type": "file", "sub_mode": "auto", "separate_first": True})]


def test_render_steps_co_buoc_tach_theo_che_do_tieng_goc():
    from backend.core.pipeline import render_steps

    cfg = {"outputs": {"dub": True}, "dub": {"voice": "A"}}
    assert "separate" in [s.key for s in render_steps(cfg)]            # mặc định voice_off
    cfg["dub"]["original_mode"] = "keep"
    assert "separate" not in [s.key for s in render_steps(cfg)]


# ------------------------------------------------------- chẻ đôi câu dài khi vẫn loạn


def test_split_middle_che_o_dau_phay_gan_giua():
    t = "Hôm nay trời đẹp quá đi mất, chúng ta cùng nhau đi dạo một vòng quanh hồ Tây nhé các bạn ơi."
    a, b = dubbing._split_middle(t)
    assert a.endswith(",") and b.startswith("chúng ta") and len(t) >= dubbing.SPLIT_MIN_CHARS
    assert dubbing._split_middle("Câu ngắn.") is None
    # không có dấu phẩy -> chẻ ở khoảng trắng gần giữa
    t2 = "một hai ba bốn năm sáu bảy tám chín mười mười một mười hai mười ba mười bốn mười lăm mười sáu"
    a2, b2 = dubbing._split_middle(t2)
    assert " " not in (a2[-1], b2[0]) and abs(len(a2) - len(b2)) < 20


class _LongEngine:
    """Câu dài (>= 90 ký tự) luôn loạn; nửa câu thì đọc bình thường."""

    def __init__(self):
        self.calls = []

    def infer(self, text, **kw):
        self.calls.append(text)
        secs = 24.0 if len(text) >= 90 else 0.6
        return np.full(int(secs * dubbing.SR), 0.2, dtype=np.float32)


def test_build_dub_track_che_doi_cau_dai_thay_vi_bo(tmp_path, monkeypatch):
    eng = _LongEngine()
    monkeypatch.setattr(dubbing, "get_engine", lambda: eng)
    monkeypatch.setattr(dubbing, "_time_stretch", lambda a, f, d, t: a)
    text = "Hôm nay trời đẹp quá đi mất, chúng ta cùng nhau đi dạo một vòng quanh hồ Tây nhé các bạn ơi."
    cues = [Cue(start=0.0, end=3.0, text="x", text2=text)]
    logs = []
    _, stats = dubbing.build_dub_track(cues, 5.0, tmp_path, voice="A", on_log=logs.append)
    assert stats["count"] == 1 and stats["runaway"] == 0
    assert len(eng.calls) == dubbing.RUNAWAY_RETRIES + 1 + 2        # 3 lần cả câu + 2 nửa
    assert any("chẻ câu" in m for m in logs)
