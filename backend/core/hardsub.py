"""Dò và che phụ đề cứng — chữ đã nung sẵn trong hình của video gốc.

Phim tải về thường đã có phụ đề tiếng gốc nung vào hình. Nung thêm phụ đề tiếng
Việt lên thì hai dòng chữ chồng nhau, đọc không nổi. Module này tìm dải chứa phụ
đề gốc, để lúc nung thì che dải đó (làm mờ hoặc phủ hộp tối) rồi đặt phụ đề mới
lên đúng chỗ.

Cách dò. Lấy một khung hình ở giữa mỗi dòng thoại (đã biết mốc từ bước nhận
dạng), đánh dấu điểm "giống nét chữ phụ đề": sáng, có viền tối sát bên, và
**mảnh** (mảng sáng to như áo trắng, bầu trời bị loại). Rồi tìm dải hàng ngang mà
ở hai câu thoại liền nhau đều dày nét chữ **nhưng nét đã đổi khác** — vì câu
thoại đổi thì chữ phụ đề đổi, còn cảnh nền trong cùng một cảnh quay thì đứng yên.

Đã thử và bỏ hai cách đơn giản hơn (đo trên 3 video có phụ đề + 2 bản cắt bỏ phụ
đề, xem tests/test_hardsub.py):
  * so khung có thoại với khung im lặng — hỏng khi phụ đề nán lại suốt khoảng lặng;
  * ngưỡng tuyệt đối cho mật độ nét — phim hoạt hình có viền đen khắp hình.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np

from . import media
from .subtitles import Cue

WIDTH = 480                 # khung được thu nhỏ về bề ngang này cho nhanh
MAX_FRAMES = 36
BRIGHT = 200                # nét chữ phụ đề: trắng / vàng
CONTRAST = 120              # ...có viền tối hẳn trong vòng 2 px
ROW_HIT = 0.015             # hàng có >= 1,5 % điểm là nét chữ...
ROW_REL = 2.0               # ...và dày gấp đôi mức trung vị các hàng của chính khung đó
SAME_IOU = 0.5              # nét ở hai câu liền nhau trùng nhau hơn ngần này = cảnh nền đứng yên
MIN_SCORE = 0.4             # đo được: có phụ đề 0,76–0,95; không có 0,00–0,14
MIN_BAND, MAX_BAND = 0.015, 0.25   # chiều cao dải hợp lệ, tính theo chiều cao khung
CENTER_TOL = 0.15           # tâm nét chữ theo chiều ngang phải cách giữa khung <= 15 %


# ------------------------------------------------------------------ lấy khung


def _size(info: dict) -> tuple[int, int]:
    w, h = int(info.get("width") or 0), int(info.get("height") or 0)
    if w <= 0 or h <= 0:
        raise ValueError("Không đọc được kích thước khung hình.")
    return WIDTH, max(2, int(round(h * WIDTH / w / 2)) * 2)


def grab_frame(video: str | Path, t: float, size: tuple[int, int]) -> np.ndarray | None:
    """Một khung xám ở giây `t`, thu về `size`. None nếu không đọc được."""
    w, h = size
    cmd = [
        media.ffmpeg_exe(), "-hide_banner", "-loglevel", "error",
        "-ss", f"{max(0.0, t):.3f}", "-i", str(video), "-frames:v", "1",
        "-vf", f"scale={w}:{h},format=gray", "-f", "rawvideo", "pipe:1",
    ]
    try:
        raw = subprocess.run(
            cmd, capture_output=True, timeout=60,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        ).stdout
    except (OSError, subprocess.TimeoutExpired):
        return None
    if len(raw) < w * h:
        return None
    return np.frombuffer(raw[: w * h], dtype=np.uint8).reshape(h, w)


def sample_times(cues: list[Cue]) -> list[float]:
    """Giữa các dòng thoại đủ dài, theo thứ tự thời gian, tối đa `MAX_FRAMES` mốc."""
    spoken = sorted((c for c in cues if c.end - c.start >= 0.6), key=lambda c: c.start)
    times = [(c.start + c.end) / 2 for c in spoken]
    if len(times) > MAX_FRAMES:
        step = len(times) / MAX_FRAMES
        times = [times[int(i * step)] for i in range(MAX_FRAMES)]
    return times


# ------------------------------------------------------------- nét chữ


def _window(a: np.ndarray, r: int, op, fill) -> np.ndarray:
    """Áp `op` (max/min/or/and) trên cửa sổ (2r+1)² quanh mỗi điểm."""
    h, w = a.shape
    pad = np.pad(a, r, mode="constant", constant_values=fill) if fill is not None else np.pad(a, r, mode="edge")
    out = a.copy()
    for dy in range(2 * r + 1):
        for dx in range(2 * r + 1):
            op(out, pad[dy:dy + h, dx:dx + w], out=out)
    return out


def text_mask(gray: np.ndarray) -> np.ndarray:
    """Điểm giống nét chữ phụ đề: sáng, có viền tối trong vòng 2 px, và nét mảnh."""
    g = gray.astype(np.int16)
    lo = _window(g, 2, np.minimum, None)
    bright = g >= BRIGHT
    # Mở ảnh (co rồi giãn 1 px): thứ còn lại là mảng sáng dày — áo trắng, mây, đèn.
    # Nét chữ phụ đề mảnh hơn 3 px nên biến mất khi co, không bị tính vào mảng dày.
    thick = _window(_window(bright, 1, np.logical_and, False), 1, np.logical_or, False)
    return bright & (g - lo >= CONTRAST) & ~thick


# ------------------------------------------------------------------ dò dải


def band_score(masks: list[np.ndarray]) -> np.ndarray:
    """Điểm "dải phụ đề" của từng hàng: tỉ lệ cặp câu liền nhau mà hàng đó dày nét
    chữ ở cả hai khung nhưng nét đã đổi (chữ mới), không phải cảnh nền đứng yên."""
    h = masks[0].shape[0]
    rows = np.stack([m.mean(axis=1) for m in masks])
    base = np.median(rows, axis=1, keepdims=True) + 0.002
    dense = (rows >= ROW_HIT) & (rows / base >= ROW_REL)
    changed = []
    for a in range(len(masks) - 1):
        b = a + 1
        # nới 1 px cho khung lấy lệch một chút
        inter = (masks[a] & _window(masks[b], 1, np.logical_or, False)).sum(axis=1)
        union = (masks[a] | masks[b]).sum(axis=1)
        iou = inter / np.maximum(union, 1)
        changed.append(dense[a] & dense[b] & (iou < SAME_IOU))
    score = np.mean(changed, axis=0) if changed else np.zeros(h)
    return np.convolve(score, np.ones(3) / 3, mode="same")


def find_band(frames: list[np.ndarray]) -> dict:
    """Tìm dải phụ đề trong các khung (theo thứ tự thời gian). Toạ độ là tỉ lệ 0–1."""
    if len(frames) < 4:
        return {"found": False, "reason": "Quá ít dòng thoại để dò phụ đề có sẵn."}
    h, w = frames[0].shape
    masks = [text_mask(f) for f in frames]
    score = band_score(masks)
    best = float(score.max())
    if best < MIN_SCORE:
        return {"found": False, "score": round(best, 3),
                "reason": "Không thấy phụ đề nung sẵn trong hình."}

    # Dải liền quanh đỉnh, cho phép đứt quãng nhỏ (khoảng giữa hai dòng chữ)
    on = score >= best * 0.4
    peak = int(score.argmax())
    y0 = y1 = peak
    slack = max(2, int(0.02 * h))
    while y0 > 0 and (on[y0 - 1] or on[max(0, y0 - 1 - slack):y0 - 1].any()):
        y0 -= 1
    while y1 < h - 1 and (on[y1 + 1] or on[y1 + 2:min(h, y1 + 2 + slack)].any()):
        y1 += 1
    while not on[y0]:
        y0 += 1
    while not on[y1]:
        y1 -= 1
    band_h = (y1 - y0 + 1) / h
    if not (MIN_BAND <= band_h <= MAX_BAND):
        return {"found": False, "score": round(best, 3),
                "reason": f"Dải chữ tìm được cao {band_h:.0%} khung — không giống phụ đề."}

    # Bề ngang: nơi nét chữ dồn lại trong dải
    cols = np.stack([m[y0:y1 + 1].mean(axis=0) for m in masks]).mean(axis=0)
    mass = np.cumsum(cols)
    if mass[-1] <= 0:
        return {"found": False, "score": round(best, 3), "reason": "Không thấy nét chữ trong dải."}
    x0 = int(np.searchsorted(mass, 0.02 * mass[-1]))
    x1 = int(np.searchsorted(mass, 0.98 * mass[-1]))
    center = float(np.searchsorted(mass, 0.5 * mass[-1])) / w
    if abs(center - 0.5) > CENTER_TOL:
        return {"found": False, "score": round(best, 3),
                "reason": "Dải chữ không canh giữa — có lẽ là vật sáng trong cảnh, không phải phụ đề."}

    # Chừa thêm cho viền chữ, dấu thanh và những câu dài hơn mẫu đã thấy
    pad_y = max(0.012, 0.3 * band_h)
    top = max(0.0, y0 / h - pad_y)
    bottom = min(1.0, (y1 + 1) / h + pad_y)
    half = max(0.15, abs(x0 / w - 0.5), abs((x1 + 1) / w - 0.5)) + 0.05
    left, right = max(0.0, 0.5 - half), min(1.0, 0.5 + half)  # phụ đề canh giữa: che đối xứng
    return {
        "found": True, "score": round(best, 3),
        "y0": round(top, 4), "y1": round(bottom, 4),
        "x0": round(left, 4), "x1": round(right, 4),
    }


def detect(video: str | Path, cues: list[Cue], info: dict | None = None) -> dict:
    """Dò dải phụ đề nung sẵn của `video`, dùng mốc thời gian của `cues`."""
    info = info or media.probe(video)
    if not info.get("width"):
        return {"found": False, "reason": "File không có hình."}
    size = _size(info)
    frames = [f for f in (grab_frame(video, t, size) for t in sample_times(cues)) if f is not None]
    out = find_band(frames)
    out["frames"] = len(frames)
    return out


# ------------------------------------------------------------------ che


MASK_MODES = ("blur", "box")


def clean_mask(raw) -> dict | None:
    """Kiểm tra cấu hình che từ giao diện. None = không che."""
    if not isinstance(raw, dict) or raw.get("mode") not in MASK_MODES:
        return None
    try:
        y0, y1 = float(raw["y0"]), float(raw["y1"])
        x0, x1 = float(raw.get("x0", 0.0)), float(raw.get("x1", 1.0))
    except (KeyError, TypeError, ValueError):
        return None
    y0, y1 = sorted((min(1.0, max(0.0, y0)), min(1.0, max(0.0, y1))))
    x0, x1 = sorted((min(1.0, max(0.0, x0)), min(1.0, max(0.0, x1))))
    if y1 - y0 < 0.005 or x1 - x0 < 0.05:
        return None
    return {"mode": raw["mode"], "y0": y0, "y1": y1, "x0": x0, "x1": x1}


def mask_filter(mask: dict, width: int, height: int) -> str:
    """Chuỗi bộ lọc ffmpeg che dải `mask` (một đầu vào, một đầu ra)."""
    def even(v):
        return max(0, int(v) // 2 * 2)

    x, y = even(mask["x0"] * width), even(mask["y0"] * height)
    w = max(2, min(width - x, even(mask["x1"] * width) - x))
    h = max(2, min(height - y, even(mask["y1"] * height) - y))
    # Làm mờ đủ mạnh để chữ cũ thành vệt mờ, rồi phủ tối cho chữ mới nổi lên. Kiểu
    # "hộp" cũng làm mờ trước: chỉ phủ hộp đen 82 % thì chữ trắng vẫn lộ ra đọc được.
    sigma = max(6, min(40, h // 3))
    dark = 0.85 if mask["mode"] == "box" else 0.28
    return (
        f"split=2[hs_base][hs_cut];"
        f"[hs_cut]crop={w}:{h}:{x}:{y},gblur=sigma={sigma}:steps=2,"
        f"drawbox=x=0:y=0:w={w}:h={h}:color=black@{dark}:t=fill[hs_blur];"
        f"[hs_base][hs_blur]overlay={x}:{y}"
    )
