"""Đỉnh sóng âm thu gọn để vẽ dòng thời gian ở bước 4.

Trình duyệt không cần cả file wav (16 phút = 30 MB) để vẽ một dải sóng rộng vài
nghìn điểm ảnh. Ở đây file được đọc từng khối, mỗi "điểm" giữ lại biên độ lớn
nhất của khoảng thời gian nó phủ, chuẩn hoá về 0–1.
"""

from __future__ import annotations

import json
import wave
from pathlib import Path

MIN_POINTS, MAX_POINTS = 200, 8000
_CHUNK_FRAMES = 1 << 18


def peaks(path: Path, points: int = 2000) -> tuple[list[float], float]:
    """Trả về ``(danh sách đỉnh 0–1, thời lượng giây)`` của một file wav PCM 16 bit."""
    import numpy as np

    points = max(MIN_POINTS, min(MAX_POINTS, int(points)))
    with wave.open(str(path), "rb") as wf:
        if wf.getsampwidth() != 2:
            raise ValueError("Chỉ đọc được wav PCM 16 bit.")
        total, channels, sr = wf.getnframes(), wf.getnchannels(), wf.getframerate()
        if total <= 0 or sr <= 0:
            return [], 0.0
        points = min(points, total)
        out = np.zeros(points, dtype=np.float32)
        done = 0
        while done < total:
            raw = wf.readframes(_CHUNK_FRAMES)
            if not raw:
                break
            block = np.abs(np.frombuffer(raw, dtype="<i2").astype(np.float32))
            if channels > 1:
                block = block.reshape(-1, channels).max(axis=1)
            # khung thứ k của cả file rơi vào điểm k * points // total
            idx = ((done + np.arange(block.size, dtype=np.int64)) * points) // total
            np.maximum.at(out, np.minimum(idx, points - 1), block)
            done += block.size
    top = float(out.max())
    if top > 0:
        out /= top
    return [round(float(v), 3) for v in out], total / sr


def cached_peaks(path: Path, points: int = 2000) -> tuple[list[float], float]:
    """Như `peaks`, có lưu kết quả cạnh file wav — mở lại dự án không phải đọc lại 30 MB."""
    path = Path(path)
    stamp = path.stat()
    cache = path.with_name(f"{path.stem}.peaks.json")
    key = [int(points), stamp.st_size, int(stamp.st_mtime)]
    try:
        saved = json.loads(cache.read_text(encoding="utf-8"))
        if saved.get("key") == key:
            return saved["peaks"], float(saved["duration"])
    except (OSError, ValueError, KeyError, TypeError):
        pass
    data, duration = peaks(path, points)
    try:
        cache.write_text(json.dumps({"key": key, "peaks": data, "duration": duration}), encoding="utf-8")
    except OSError:
        pass  # không ghi được cache thì lần sau tính lại, không sao
    return data, duration
