"""Nhận dạng giọng nói bằng faster-whisper (CTranslate2).

Điểm quan trọng: Whisper có thể **bỏ sót cả đoạn dài mà không báo lỗi** — nhất
là video ca nhạc, vì bộ lọc VAD tưởng phần hát là "không có tiếng nói". Module
này luôn đo độ phủ thời gian, tự chạy lại khi phủ thấp, và quét bù các khoảng
trống lớn còn sót.
"""

from __future__ import annotations

import os
import sys
import threading
from pathlib import Path
from typing import Callable

from . import hf_cache
from ..config import MODEL_DIR

_lock = threading.Lock()
_cache: dict[tuple, object] = {}
_dll_ready = False
_cache_checked = False
# GPU nhận ra được nhưng tính toán thì lỗi (thiếu cuBLAS/cuDNN, hết VRAM…).
# Biết rồi thì lần sau chọn CPU luôn thay vì lại thất bại giữa đường.
_cuda_broken = False

# Coi là "hụt" nếu phụ đề phủ dưới ngần này so với thời lượng video
COVERAGE_TARGET = 0.85
# Khoảng trống dài hơn ngần này (giây) thì quét bù. Để 3,5s: đo trên video thật
# (recap phim nhanh, nhạc nền to) thấy nhiều đoạn thoại 4–13s lọt lưới vì ngưỡng
# cũ 20s — khán giả nghe nguyên tiếng gốc chưa dịch ở mấy đoạn đó.
GAP_RESCAN = 3.5
# Quét bù tối đa ngần này khoảng trống một lần, để video im lặng dài không kéo
# thời gian nhận dạng lên vô tận.
GAP_RESCAN_MAX = 40
# Ngưỡng lọc kết quả quét bù, tránh Whisper bịa lời trên đoạn nhạc/im lặng.
# no_speech nới tới 0,85: lời HÁT hoặc thoại đè nhạc to bị Whisper chấm
# no_speech rất cao (đo thật: "我愛你" hát trên nhạc = 0,84) tuy vẫn là tiếng
# người thật. Chốt chặn thứ thiệt là tỉ lệ nén: lời bịa trên nhạc luôn lặp đi
# lặp lại nên nén rất cao.
RESCAN_MAX_NO_SPEECH = 0.85
RESCAN_MIN_LOGPROB = -1.2
# Đoạn có tỉ lệ nén cao hơn ngần này là văn bản lặp — dấu hiệu Whisper bịa
# (chuẩn của openai-whisper). Onomatopoeia lặp ("啪啪啪…") cũng rơi vào đây,
# bỏ đúng vì đó là tiếng động chứ không phải thoại.
RESCAN_MAX_COMPRESSION = 2.4


# Câu Whisper hay bịa trên nhạc/đoạn lặng: dòng ghi công người làm phụ đề và lời
# kêu gọi đăng ký kênh. Thoại phim gần như không bao giờ chứa mấy chữ này, nên
# thấy là bỏ — kể cả khi độ tin cao. (Đo thật trên video mẫu bắt được
# "字幕by索兰娅" và "請不吝點贊訂閱轉發打賞…".)
_HALLUCINATION_MARKERS = (
    "字幕", "订阅", "訂閱", "点赞", "點贊", "打赏", "打賞", "转发", "轉發",
    "明镜", "明鏡", "点点栏目", "點點欄目", "字幕组", "字幕組", "志愿者", "志願者",
    "谢谢观看", "謝謝觀看", "感谢观看", "感謝觀看", "关注", "關注",
    "amara", "subscribe", "subtitles by", "thanks for watching",
)


def _is_boilerplate(text: str) -> bool:
    low = text.lower()
    return any(m in low for m in _HALLUCINATION_MARKERS)


def looks_like_speech(seg: dict) -> bool:
    """Đoạn quét bù này là tiếng người thật, hay Whisper bịa trên nhạc/im lặng?

    Ưu tiên KHÔNG bỏ sót thoại thật: mất một đoạn thoại là khán giả nghe tiếng
    gốc chưa dịch, còn lỡ giữ một dòng bịa thì người dùng xoá tay ở bước 4. Nên
    ngưỡng nới rộng, chỉ chặn những thứ chắc chắn là rác: văn bản lặp (nén cao),
    độ tin quá thấp, và mấy câu ghi công / kêu gọi đăng ký kênh Whisper hay bịa.
    """
    text = (seg.get("text") or "").strip()
    if not text:
        return False
    if _is_boilerplate(text):
        return False
    if seg.get("compression_ratio", 1.0) > RESCAN_MAX_COMPRESSION:
        return False
    if seg.get("avg_logprob", 0.0) < RESCAN_MIN_LOGPROB:
        return False
    if seg.get("no_speech_prob", 0.0) > RESCAN_MAX_NO_SPEECH:
        return False
    return True


def _prepare_cuda_dlls() -> None:
    """Nạp cuBLAS/cuDNN từ các wheel nvidia-* (Windows cần add_dll_directory)."""
    global _dll_ready
    if _dll_ready:
        return
    _dll_ready = True
    if sys.platform != "win32":
        return
    try:
        import nvidia  # type: ignore
    except Exception:
        return
    # `nvidia` là namespace package -> __file__ là None, phải đọc __path__
    roots = [Path(p) for p in getattr(nvidia, "__path__", [])]
    if not roots and getattr(nvidia, "__file__", None):
        roots = [Path(nvidia.__file__).parent]
    for base in roots:
        for sub in ("cublas", "cudnn", "cuda_runtime", "cuda_nvrtc"):
            binpath = base / sub / "bin"
            if binpath.is_dir():
                try:
                    os.add_dll_directory(str(binpath))
                except Exception:
                    pass
                os.environ["PATH"] = str(binpath) + os.pathsep + os.environ.get("PATH", "")


def _repair_model_cache(on_log=None) -> None:
    """Dựng lại symlink cache HuggingFace bị dẹp (xem app/hf_cache.py)."""
    global _cache_checked
    if _cache_checked:
        return
    _cache_checked = True
    try:
        fixed = hf_cache.repair(MODEL_DIR)
    except Exception:
        return
    if fixed and on_log:
        on_log(f"Đã sửa {len(fixed)} file model bị mất liên kết trong cache.")


def gpu_available() -> bool:
    if _cuda_broken:
        return False
    try:
        import ctranslate2

        return ctranslate2.get_cuda_device_count() > 0
    except Exception:
        return False


# Thư viện CUDA thiếu chỉ bung lỗi lúc tính toán thật, không phải lúc nạp model
# — nên phải bắt ở chỗ transcribe mới rơi về CPU được.
_CUDA_ERROR_HINTS = ("cublas", "cudnn", "cudart", "cuda", "libcu", "gpu")


def _is_cuda_failure(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(hint in msg for hint in _CUDA_ERROR_HINTS)


def _forget_cuda_model(size: str) -> None:
    """Bỏ model CUDA khỏi cache và ghi nhận GPU không dùng được."""
    global _cuda_broken
    _cuda_broken = True
    with _lock:
        for key in [k for k in _cache if k[0] == size and k[1] == "cuda"]:
            _cache.pop(key, None)


def load_model(size: str = "medium", device: str = "auto", on_log=None):
    """Nạp (và cache) model Whisper. device: auto | cuda | cpu"""
    from faster_whisper import WhisperModel

    _prepare_cuda_dlls()
    _repair_model_cache(on_log)

    if device == "auto":
        device = "cuda" if gpu_available() else "cpu"
    compute = "float16" if device == "cuda" else "int8"
    key = (size, device, compute)

    with _lock:
        if key in _cache:
            return _cache[key], device

        try:
            model = WhisperModel(
                size, device=device, compute_type=compute, download_root=str(MODEL_DIR)
            )
        except Exception:
            if device != "cpu":
                # GPU hỏng (thiếu cuDNN, hết VRAM...) -> rơi về CPU
                device, compute = "cpu", "int8"
                key = (size, device, compute)
                if key in _cache:
                    return _cache[key], device
                model = WhisperModel(
                    size, device="cpu", compute_type="int8", download_root=str(MODEL_DIR)
                )
            else:
                raise
        _cache[key] = model
        return model, device


# ------------------------------------------------------------------ tiện ích


def _collect(segments, on_seg=None) -> list[dict]:
    """Đổi generator segment của faster-whisper thành list dict thuần."""
    out: list[dict] = []
    for seg in segments:
        item = {
            "start": float(seg.start),
            "end": float(seg.end),
            "text": seg.text,
            "no_speech_prob": float(getattr(seg, "no_speech_prob", 0.0) or 0.0),
            "avg_logprob": float(getattr(seg, "avg_logprob", 0.0) or 0.0),
            "compression_ratio": float(getattr(seg, "compression_ratio", 1.0) or 1.0),
            "words": [
                {"word": w.word, "start": float(w.start), "end": float(w.end)}
                for w in (seg.words or [])
                if w.word is not None and w.start is not None and w.end is not None
            ],
        }
        out.append(item)
        if on_seg:
            on_seg(item)
    return out


def voiced_time(segs: list[dict]) -> float:
    """Tổng thời lượng có lời (đã gộp các đoạn chồng nhau)."""
    if not segs:
        return 0.0
    merged: list[list[float]] = []
    for s in sorted(segs, key=lambda x: x["start"]):
        if merged and s["start"] <= merged[-1][1] + 0.01:
            merged[-1][1] = max(merged[-1][1], s["end"])
        else:
            merged.append([s["start"], s["end"]])
    return sum(b - a for a, b in merged)


def coverage(segs: list[dict], duration: float) -> float:
    """Phụ đề chạy tới đâu so với thời lượng video (0..1)."""
    if not segs or duration <= 0:
        return 0.0
    return min(1.0, max(s["end"] for s in segs) / duration)


def find_gaps(segs: list[dict], duration: float, min_gap: float = GAP_RESCAN) -> list[tuple]:
    """Các khoảng trống dài trong timeline, kể cả phần đầu và phần đuôi."""
    gaps: list[tuple] = []
    prev = 0.0
    for s in sorted(segs, key=lambda x: x["start"]):
        if s["start"] - prev >= min_gap:
            gaps.append((prev, s["start"]))
        prev = max(prev, s["end"])
    if duration - prev >= min_gap:
        gaps.append((prev, duration))
    return gaps


# ------------------------------------------------------------------ 1 lượt


def _one_pass(
    model,
    audio_path: str,
    language: str | None,
    vad: bool,
    initial_prompt: str | None,
    total: float,
    clip: tuple[float, float] | None = None,
    on_progress: Callable[[float], None] | None = None,
) -> tuple[list[dict], object]:
    kwargs = dict(
        language=language,
        task="transcribe",
        beam_size=5,
        word_timestamps=True,
        condition_on_previous_text=False,
        initial_prompt=initial_prompt or None,
    )
    if vad:
        kwargs["vad_filter"] = True
        kwargs["vad_parameters"] = {"min_silence_duration_ms": 500}
    else:
        kwargs["vad_filter"] = False
        # Không có VAD thì nới ngưỡng để không bỏ rơi đoạn hát / nhạc nền to
        kwargs["no_speech_threshold"] = 0.9
    if clip:
        kwargs["clip_timestamps"] = [float(clip[0]), float(clip[1])]

    segments, info = model.transcribe(audio_path, **kwargs)

    lo = clip[0] if clip else 0.0
    hi = clip[1] if clip else (total or 0.0)
    span = max(0.1, hi - lo)

    def report(item: dict) -> None:
        if on_progress:
            on_progress(min(1.0, (item["end"] - lo) / span))

    segs = _collect(segments, report)
    if on_progress:
        on_progress(1.0)
    return segs, info


# ------------------------------------------------------------------ chính


def transcribe(
    audio_path: str | Path,
    language: str | None = None,
    model_size: str = "medium",
    device: str = "auto",
    duration: float = 0.0,
    vad: bool = False,
    initial_prompt: str | None = None,
    auto_fix: bool = True,
    on_progress: Callable[[float], None] | None = None,
    on_log: Callable[[str], None] | None = None,
) -> dict:
    """Trả về {language, duration, words, segments, coverage, ...}

    `auto_fix=True`: nếu độ phủ thấp thì tự chạy lại không dùng VAD, rồi quét bù
    các khoảng trống lớn còn sót. Đây là thứ chặn lỗi "video dài nhưng chỉ ra
    phụ đề cho vài chục giây đầu".
    """
    audio_path = str(audio_path)
    model, used_device = load_model(model_size, device, on_log=on_log)
    if on_log:
        on_log(f"Whisper `{model_size}` chạy trên {used_device.upper()}"
               + (" (có lọc VAD)" if vad else ""))

    # ------- lượt 1
    def p1(x: float) -> None:
        if on_progress:
            on_progress(x * (0.65 if auto_fix else 1.0))

    try:
        segs, info = _one_pass(model, audio_path, language, vad, initial_prompt, duration, None, p1)
    except Exception as exc:
        if used_device == "cpu" or not _is_cuda_failure(exc):
            raise
        # GPU chào hàng được nhưng chạy không nổi -> làm lại bằng CPU
        if on_log:
            on_log(f"GPU không dùng được: {exc}")
            on_log("Chuyển sang CPU và nhận dạng lại (chậm hơn nhưng vẫn ra kết quả)…")
        _forget_cuda_model(model_size)
        model, used_device = load_model(model_size, "cpu", on_log=on_log)
        segs, info = _one_pass(model, audio_path, language, vad, initial_prompt, duration, None, p1)

    total = duration or float(getattr(info, "duration", 0.0) or 0.0)
    detected = getattr(info, "language", None) or language
    notes: list[str] = []

    cov = coverage(segs, total)
    if on_log:
        on_log(f"Lượt 1: {len(segs)} đoạn, phụ đề phủ {cov * 100:.0f}% thời lượng video.")

    # ------- lượt 2: phủ thấp và đang bật VAD -> chạy lại không VAD
    if auto_fix and vad and cov < COVERAGE_TARGET and total > 0:
        if on_log:
            on_log(
                f"Độ phủ chỉ {cov * 100:.0f}% — bộ lọc VAD có thể đã cắt mất phần hát/"
                "nhạc nền. Đang nhận dạng lại không dùng VAD…"
            )

        def p2(x: float) -> None:
            if on_progress:
                on_progress(0.65 + x * 0.2)

        alt, alt_info = _one_pass(model, audio_path, language, False, initial_prompt, total, None, p2)
        if voiced_time(alt) > voiced_time(segs) * 1.1:
            segs, info = alt, alt_info
            detected = getattr(alt_info, "language", None) or detected
            cov = coverage(segs, total)
            notes.append("đã tắt VAD vì độ phủ thấp")
            if on_log:
                on_log(f"Dùng kết quả không VAD: {len(segs)} đoạn, phủ {cov * 100:.0f}%.")
        elif on_log:
            on_log("Chạy lại không giúp thêm — giữ kết quả ban đầu.")
    elif auto_fix and on_progress:
        on_progress(0.85)

    # ------- lượt 3: quét bù các khoảng trống lớn
    if auto_fix and total > 0:
        gaps = [g for g in find_gaps(segs, total) if g[1] - g[0] >= GAP_RESCAN][:GAP_RESCAN_MAX]
        if gaps:
            if on_log:
                pretty = ", ".join(f"{int(a)}–{int(b)}s" for a, b in gaps[:5])
                on_log(f"Còn {len(gaps)} khoảng trống ({pretty}"
                       + ("…" if len(gaps) > 5 else "") + ") — đang quét bù…")
            added = 0
            for gi, (a, b) in enumerate(gaps):
                def p3(x: float, gi=gi) -> None:
                    if on_progress:
                        on_progress(0.85 + (gi + x) / len(gaps) * 0.15)

                try:
                    extra, _ = _one_pass(
                        model, audio_path, language, False, initial_prompt, total, (a, b), p3
                    )
                except Exception as exc:
                    if on_log:
                        on_log(f"Quét bù {int(a)}–{int(b)}s lỗi, bỏ qua: {exc}")
                    continue
                # Giữ đoạn nào nghe như tiếng người thật, bỏ đoạn Whisper bịa
                # trên nhạc/im lặng (xem looks_like_speech).
                keep = [s for s in extra if looks_like_speech(s)]
                segs.extend(keep)
                added += len(keep)
            if added:
                segs.sort(key=lambda s: s["start"])
                cov = coverage(segs, total)
                notes.append(f"quét bù thêm {added} đoạn")
                if on_log:
                    on_log(f"Quét bù thêm được {added} đoạn — phủ {cov * 100:.0f}%.")
            elif on_log:
                on_log("Các khoảng trống đó thật sự không có lời (nhạc/im lặng).")

    if on_progress:
        on_progress(1.0)

    words: list[dict] = []
    for s in segs:
        if s["words"]:
            words.extend(s["words"])
        else:
            words.append({"word": s["text"], "start": s["start"], "end": s["end"]})
    words.sort(key=lambda w: w["start"])

    voiced = voiced_time(segs)
    if on_log and total:
        on_log(
            f"Kết quả: {len(segs)} đoạn, {voiced:.0f}s có lời trên tổng {total:.0f}s "
            f"(phủ tới {cov * 100:.0f}%)."
        )

    return {
        "language": detected,
        "language_probability": float(getattr(info, "language_probability", 0.0) or 0.0),
        "duration": total,
        "words": words,
        "segments": [{"start": s["start"], "end": s["end"], "text": s["text"]} for s in segs],
        "device": used_device,
        "coverage": cov,
        "voiced": voiced,
        "notes": notes,
        "gaps": [(round(a, 1), round(b, 1)) for a, b in find_gaps(segs, total)],
    }
