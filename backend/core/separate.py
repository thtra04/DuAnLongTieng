"""Tách giọng nói gốc ra khỏi nhạc nền và tiếng động (Demucs, model htdemucs).

Dùng cho lồng tiếng: bỏ hẳn thoại gốc, giữ nguyên nhạc và tiếng động, rồi đặt giọng
mới lên. Trước đây tool chỉ hạ nhỏ tiếng gốc (ducking) nên hai giọng vẫn chồng nhau.

Hai sản phẩm phụ cũng có ích:

* ``vocals.wav`` sạch nhạc -> cắt mẫu nhân bản giọng tốt hơn (mẫu không lẫn nhạc).
* ``no_vocals.wav`` -> nền để trộn với giọng mới.

Chạy trên CPU: ~0,8× thời lượng (đo 18/10/2026: 88 s tiếng mất 71 s). Model ~80 MB tải
về MODEL_DIR/torch lần đầu (TORCH_HOME đặt ở config.py).
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path
from typing import Callable

from . import media

MODEL = "htdemucs"
SR = 44100


def available() -> tuple[bool, str]:
    try:
        import torch  # noqa: F401
        import demucs.api  # noqa: F401
    except Exception as exc:
        return False, f"Chưa cài demucs/torch ({exc.__class__.__name__}). Cài extra `separate`."
    return True, ""


def _extract_stereo(video: Path, out_wav: Path) -> Path:
    """Tiếng của video -> WAV 44,1 kHz stereo (định dạng Demucs được huấn luyện)."""
    subprocess.run(
        [media.ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
         "-i", str(Path(video).resolve()), "-vn", "-ac", "2", "-ar", str(SR), "-c:a", "pcm_s16le",
         str(out_wav.resolve())],
        check=True, capture_output=True, creationflags=(0x08000000 if sys.platform == "win32" else 0),
    )
    return out_wav


def split_vocals(
    source: str | Path,
    workdir: str | Path,
    on_progress: Callable[[float], None] | None = None,
    on_log: Callable[[str], None] | None = None,
    reuse_from: list[Path] | None = None,
) -> tuple[Path, Path]:
    """Tách `source` (video hoặc audio) thành ``(vocals.wav, no_vocals.wav)`` trong `workdir`.

    Đã có hai file từ lần trước thì trả luôn, không tách lại (tách 16 phút mất ~14 phút).
    `reuse_from`: các thư mục khác (vd. thư mục dự án phân tích) có thể đã có sẵn hai file này —
    chép sang `workdir` rồi dùng, khỏi tách lại.
    """
    workdir = Path(workdir)
    vocals, rest = workdir / "vocals.wav", workdir / "no_vocals.wav"

    def have(d: Path) -> bool:
        v, r = d / "vocals.wav", d / "no_vocals.wav"
        return v.exists() and r.exists() and v.stat().st_size > 1024

    if have(workdir):
        if on_log:
            on_log("Đã tách giọng gốc ở lần trước — dùng lại.")
        return vocals, rest
    for d in reuse_from or []:
        d = Path(d)
        if d != workdir and have(d):
            shutil.copy(d / "vocals.wav", vocals)
            shutil.copy(d / "no_vocals.wav", rest)
            if on_log:
                on_log("Dùng lại phần giọng / nền đã tách lúc phân tích video.")
            return vocals, rest

    import torch
    from demucs.api import Separator, save_audio

    mix = _extract_stereo(Path(source), workdir / "mix44.wav")
    done = {"seconds": 0.0}

    def cb(info: dict) -> None:
        # Demucs gọi lại ở đầu/cuối mỗi đoạn; audio_length và segment_offset tính theo mẫu
        if on_progress and info.get("state") == "end":
            total = float(info.get("audio_length") or 0)
            if total > 0:
                frac = (float(info.get("segment_offset", 0)) + float(info.get("segment_length", 0))) / total
                on_progress(max(0.0, min(0.99, frac)))

    sep = Separator(model=MODEL, device="cpu", shifts=0, overlap=0.2, progress=False, callback=cb)
    if on_log:
        on_log(f"Tách giọng gốc khỏi nhạc nền bằng Demucs ({MODEL}) — chạy trên CPU, chờ khoảng "
               "bằng thời lượng video…")
    origin, stems = sep.separate_audio_file(mix)
    voc = stems["vocals"]
    save_audio(voc, vocals, samplerate=sep.samplerate, clip="rescale")
    save_audio(origin - voc, rest, samplerate=sep.samplerate, clip="rescale")
    del origin, stems, voc
    mix.unlink(missing_ok=True)
    if on_progress:
        on_progress(1.0)
    return vocals, rest
