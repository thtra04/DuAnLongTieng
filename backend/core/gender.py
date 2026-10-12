"""Đoán giọng nam / nữ của từng dòng thoại từ cao độ giọng (F0).

Mục đích: lúc lồng tiếng, nhân vật nam được đọc bằng giọng nam, nhân vật nữ bằng
giọng nữ — kể cả khi chưa cài được mô hình phân đoạn người nói (pyannote cần
torch và token Hugging Face). Module này chỉ cần numpy.

Luồng::

    audio.wav  ->  cắt đúng khoảng của từng cue  ->  F0 từng khung 40 ms
               ->  trung vị F0 các khung hữu thanh ->  < 165 Hz: nam, còn lại: nữ

Hai cách dùng:

* **Chưa có nhãn nhân vật** (`split_cues`): chia cue thành hai nhóm nam / nữ, gán
  nhãn `S1`, `S2` theo tổng thời gian nói — dùng lại nguyên bảng "giọng cho từng
  nhân vật" sẵn có.
* **Đã có nhãn từ phân đoạn người nói** (`speaker_genders`): gộp F0 của mọi cue
  cùng một người rồi mới quyết, nên chắc hơn hẳn quyết theo từng câu.

Giới hạn cần biết: F0 không phân biệt được hai người cùng giới, giọng trẻ em
thường rơi vào nhóm nữ, và nhạc nền to có thể kéo lệch cao độ của câu ngắn. Vì
vậy cue có quá ít khung hữu thanh thì **để trống** chứ không đoán bừa.
"""

from __future__ import annotations

import wave
from pathlib import Path

import numpy as np

from .subtitles import Cue

# Dải cao độ của tiếng nói người lớn; ngoài dải này thường là nhạc hoặc nhiễu
F0_MIN, F0_MAX = 70.0, 400.0
# Ranh nam / nữ. Nam trưởng thành ~85–155 Hz, nữ ~165–255 Hz.
SPLIT_HZ = 165.0
FRAME_S, HOP_S = 0.040, 0.010
# Đỉnh tự tương quan chuẩn hoá từ ngần này trở lên mới coi là khung hữu thanh
VOICED_PEAK = 0.5
# Đỉnh sớm hơn phải đạt tỉ lệ này so với đỉnh cao nhất mới được chọn thay. Đo trên
# thoại thật: 0,90 kéo giọng nam lên một quãng tám (đỉnh ở T/2 của hoạ âm bậc hai),
# 0,97 thì không; còn với tín hiệu tuần hoàn sạch, đỉnh T và 2T chỉ lệch nhau < 1 %.
EARLY_PEAK = 0.97
# Ít hơn ngần này khung hữu thanh (~0,12 s) thì không đủ căn cứ để đoán
MIN_VOICED = 12

MALE, FEMALE = "M", "F"
NAMES = {MALE: "Nam", FEMALE: "Nữ"}


# ------------------------------------------------------------------ cao độ


def frame_pitches(x: np.ndarray, sr: int) -> np.ndarray:
    """F0 (Hz) của các khung hữu thanh trong `x`, bằng tự tương quan.

    Tự tương quan tính qua FFT cho cả lô khung một lượt, rồi chia cho tự tương
    quan của chính cửa sổ Hann — không chia thì độ trễ dài bị dìm xuống và giọng
    nam trầm hay bị nhận nhầm lên một quãng tám.
    """
    n, hop = int(FRAME_S * sr), int(HOP_S * sr)
    x = np.asarray(x, dtype=np.float32).reshape(-1)
    if x.size < n:
        return np.empty(0, dtype=np.float32)

    frames = np.lib.stride_tricks.sliding_window_view(x, n)[::hop]
    frames = frames - frames.mean(axis=1, keepdims=True)
    rms = np.sqrt((frames ** 2).mean(axis=1))
    # Bỏ khung quá nhỏ: tự tương quan của tiếng ồn nền vẫn có đỉnh giả
    loud = rms > max(0.005, 0.2 * float(np.percentile(rms, 90)))
    if not loud.any():
        return np.empty(0, dtype=np.float32)

    win = np.hanning(n).astype(np.float32)
    nfft = 1 << (2 * n - 1).bit_length()
    spec = np.fft.rfft(frames[loud] * win, nfft, axis=1)
    ac = np.fft.irfft(spec.real ** 2 + spec.imag ** 2, axis=1)[:, :n]
    wspec = np.fft.rfft(win, nfft)
    wac = np.fft.irfft(wspec.real ** 2 + wspec.imag ** 2)[:n]
    ac = ac / (ac[:, :1] + 1e-12) / (wac / wac[0])

    lo, hi = int(sr / F0_MAX), min(int(sr / F0_MIN), n - 1)
    seg = ac[:, lo:hi + 1]
    peak = seg.max(axis=1)
    # Tín hiệu tuần hoàn có đỉnh ở cả T, 2T, 3T… gần bằng nhau; lấy thẳng argmax thì
    # hay rơi vào 2T (cao độ bị chia đôi, nữ thành nam). Lấy đỉnh SỚM NHẤT gần bằng
    # đỉnh cao nhất (EARLY_PEAK), rồi dò thêm vài mẫu để tới đúng chóp của nó.
    first = (seg >= EARLY_PEAK * peak[:, None]).argmax(axis=1)
    near = np.minimum(first[:, None] + np.arange(4), seg.shape[1] - 1)
    lag = np.take_along_axis(near, np.take_along_axis(seg, near, axis=1).argmax(axis=1)[:, None], axis=1)[:, 0] + lo
    voiced = peak >= VOICED_PEAK
    return (sr / lag[voiced]).astype(np.float32)


def measure(wav_path: str | Path, cues: list[Cue]) -> list[dict]:
    """Đo cao độ từng cue. Trả về ``[{"f0": Hz hoặc 0.0, "voiced": số khung}]``.

    Đọc đúng khoảng của từng cue chứ không nạp cả file: đường tiếng của một tập
    phim 9 tiếng là mảng ~2 GB, trong khi mỗi cue chỉ vài giây.
    """
    out: list[dict] = []
    with wave.open(str(wav_path), "rb") as w:
        sr, ch, sw, total = w.getframerate(), w.getnchannels(), w.getsampwidth(), w.getnframes()
        if sw != 2:
            raise ValueError("Chỉ đọc được WAV 16-bit.")
        for cue in cues:
            a = max(0, min(total, int(cue.start * sr)))
            b = max(a, min(total, int(cue.end * sr)))
            if b - a < int(FRAME_S * sr):
                out.append({"f0": 0.0, "voiced": 0})
                continue
            w.setpos(a)
            x = np.frombuffer(w.readframes(b - a), dtype="<i2").astype(np.float32) / 32768.0
            if ch > 1:
                x = x.reshape(-1, ch).mean(axis=1)
            f0 = frame_pitches(x, sr)
            out.append({
                "f0": round(float(np.median(f0)), 1) if f0.size >= MIN_VOICED else 0.0,
                "voiced": int(f0.size),
            })
    return out


def gender_of(f0: float) -> str:
    """`"M"`, `"F"`, hoặc `""` khi không có cao độ đáng tin."""
    if not f0 or f0 <= 0:
        return ""
    return MALE if f0 < SPLIT_HZ else FEMALE


# ------------------------------------------------------------- gán vào cue


def _weighted_median(values: list[float], weights: list[float]) -> float:
    order = np.argsort(values)
    v, w = np.asarray(values)[order], np.asarray(weights, dtype=np.float64)[order]
    cut = np.searchsorted(np.cumsum(w), w.sum() / 2.0)
    return float(v[min(cut, len(v) - 1)])


def speaker_genders(cues: list[Cue], pitches: list[dict]) -> dict[str, dict]:
    """Giới tính của từng nhân vật đã có nhãn: ``{nhãn: {"gender", "f0"}}``.

    Lấy trung vị F0 của các cue cùng nhãn, có trọng số là số khung hữu thanh —
    câu dài, rõ tiếng nặng ký hơn tiếng "ừ" nửa giây.
    """
    grouped: dict[str, tuple[list[float], list[float]]] = {}
    for cue, p in zip(cues, pitches):
        sid = (cue.speaker or "").strip()
        if sid and p["f0"] > 0:
            vals, wts = grouped.setdefault(sid, ([], []))
            vals.append(p["f0"])
            wts.append(p["voiced"])
    out: dict[str, dict] = {}
    for sid in {(c.speaker or "").strip() for c in cues} - {""}:
        if sid in grouped:
            f0 = _weighted_median(*grouped[sid])
            out[sid] = {"gender": gender_of(f0), "f0": round(f0, 1)}
        else:
            out[sid] = {"gender": "", "f0": 0.0}
    return out


def split_cues(cues: list[Cue], pitches: list[dict]) -> dict:
    """Chia cue thành nhóm nam / nữ khi chưa có nhãn nhân vật. Sửa `cues` tại chỗ.

    Nhóm nói nhiều hơn mang nhãn `S1`, nhóm kia `S2` — cùng quy ước với phân
    đoạn người nói, để bảng giọng ở bước 4 dùng lại được. Cue không đủ căn cứ
    thì để trống, lúc lồng tiếng sẽ đọc bằng giọng chung.

    Trả về ``{"total", "labeled", "empty", "genders": {nhãn: "M"|"F"}, "f0": {nhãn: Hz}}``.
    """
    stats = {"total": len(cues), "labeled": 0, "empty": 0, "genders": {}, "f0": {}}
    talk = {MALE: 0.0, FEMALE: 0.0}
    guess: list[str] = []
    for cue, p in zip(cues, pitches):
        g = gender_of(p["f0"])
        guess.append(g)
        if g:
            talk[g] += max(0.0, cue.end - cue.start)

    order = sorted((g for g in talk if talk[g] > 0), key=lambda g: (-talk[g], g))
    label = {g: f"S{i}" for i, g in enumerate(order, 1)}
    for cue, g in zip(cues, guess):
        cue.speaker = label.get(g, "")
        if cue.speaker:
            stats["labeled"] += 1
        else:
            stats["empty"] += 1
    stats["genders"] = {lab: g for g, lab in label.items()}
    for g, lab in label.items():
        vals = [(p["f0"], p["voiced"]) for p, x in zip(pitches, guess) if x == g]
        stats["f0"][lab] = round(_weighted_median([v for v, _ in vals], [w for _, w in vals]), 1)
    return stats


# --------------------------------------------------------------- chọn giọng


def voice_gender(label: str) -> str:
    """Giới tính của một giọng dựng sẵn, đọc từ nhãn kiểu ``"Tên — Nam · Bắc · …"``."""
    tail = str(label or "").split("—", 1)[-1].replace("-", " ")
    first = tail.strip().split("·", 1)[0].strip().lower()
    if first == "nam":
        return MALE
    if first in ("nữ", "nu"):
        return FEMALE
    return ""


def pick_voice(voices: list[dict], gender: str, taken: set[str] | None = None) -> str:
    """Id giọng dựng sẵn hợp giới tính, ưu tiên giọng chưa ai dùng. `""` nếu không có.

    Không chọn theo cao độ: đã thử lấy giọng có cao độ gần giọng gốc nhất, đo bằng
    véc-tơ đặc trưng giọng (pyannote WeSpeaker) trên clip mẫu thì độ giống giọng gốc
    còn THẤP hơn (0,26/0,34 so với 0,41/0,37). Muốn giống giọng gốc thì nhân bản.
    """
    same = [v for v in voices if (v.get("gender") or voice_gender(v.get("label", ""))) == gender]
    if not gender or not same:
        return ""
    taken = taken or set()
    for v in same:
        if v["id"] not in taken:
            return v["id"]
    return same[0]["id"]
