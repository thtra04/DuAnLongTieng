"""Nhận dạng giọng nói bằng faster-whisper (CTranslate2).

Điểm quan trọng: Whisper có thể **bỏ sót cả đoạn dài mà không báo lỗi** — nhất
là video ca nhạc, vì bộ lọc VAD tưởng phần hát là "không có tiếng nói". Module
này luôn đo độ phủ thời gian, tự chạy lại khi phủ thấp, và quét bù các khoảng
trống lớn còn sót.
"""

from __future__ import annotations

import os
import re
import sys
import threading
import wave
from pathlib import Path
from typing import Callable

from . import hf_cache
from ..config import MODEL_DIR
from .languages import name_vi

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
SPEECH_GAP_MIN = 0.65
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
    # Đo thật (phim Thái The Rules EP5): Whisper bịa "โปรดติดตามตอนต่อไป" ("mời đón
    # xem tập sau") 7 lần trên đoạn nhạc, và "Thank you for watching. See you in the
    # next video." trên nhạc mở đầu khi dò nhầm ngôn ngữ.
    "โปรดติดตามตอนต่อไป", "โปรดติดตามต่อไป", "ติดตามชม", "ขอบคุณที่รับชม", "กดติดตาม",
    "thank you for watching", "see you in the next video",
)

# Dò ngôn ngữ trên các khúc có tiếng người trong ngần này giây đầu video...
LANG_PROBE_SPAN = 600.0
# ...cộng xác suất của tối đa ngần này khúc 30 s.
LANG_PROBE_WINDOWS = 3
# Ít tiếng người hơn ngần này (giây) thì không dò được — để faster-whisper tự dò như cũ.
LANG_PROBE_MIN_SPEECH = 3.0
# Ngôn ngữ medium nhận dạng đã tốt (đo trên bench tiếng Trung: medium 92,3 % dòng đúng,
# large-v3 93,1 %). Ngôn ngữ khác mà đang để medium thì tự đổi sang large-v3 khi chạy GPU
# và model đã có trên máy. Đo thật cả tập phim Thái 40 phút, cùng code: phụ đề đúng ý
# 56 % → 72 % / 108 câu gold, dòng lẫn rác 41 → 25, khâu nghe lâu hơn ~30 % (RTX 4060).
STRONG_MEDIUM_LANGS = ("zh", "en")
_SMALL_MODELS = ("tiny", "base", "small", "medium")
UPGRADE_FROM = "medium"
UPGRADE_TO = "large-v3"
# Đặt VSUB_ASR_AUTO_UPGRADE=0 để luôn chạy đúng model đã chọn.
AUTO_UPGRADE = os.environ.get("VSUB_ASR_AUTO_UPGRADE", "1") != "0"


def _is_boilerplate(text: str) -> bool:
    low = text.strip().lower().strip(".!?…。！？ ")
    # A word like "关注" (pay attention) or the name Amara can be real dialogue.
    return (low in _HALLUCINATION_MARKERS
            or re.fullmatch(r"x+d{2,}", low) is not None
            or low.startswith(("字幕by", "字幕组:", "字幕組：", "subtitles by "))
            or sum(m in low for m in ("點贊", "訂閱", "轉發", "打賞", "点赞", "订阅", "转发", "打赏")) >= 3
            or low == "thank you for watching. see you in the next video")


def _drop_boilerplate(segs: list[dict], notes: list[str], on_log=None) -> list[dict]:
    """Bỏ các câu Whisper hay bịa (ghi công, "đón xem tập sau"…) ngay ở lượt chính.

    Trước đây chỉ lượt quét bù mới lọc, nên câu bịa ở lượt 1 lọt thẳng ra phụ đề
    (đo thật: 7 dòng "โปรดติดตามตอนต่อไป" trong 8 phút đầu phim Thái).
    """
    kept = [s for s in segs if not _is_boilerplate(s.get("text") or "")]
    dropped = len(segs) - len(kept)
    if dropped:
        notes.append(f"bỏ {dropped} câu Whisper bịa")
        if on_log:
            on_log(f"Bỏ {dropped} câu Whisper hay bịa trên nhạc/đoạn lặng "
                   "(kiểu “đón xem tập sau”, “cảm ơn đã xem”).")
    return kept


def _suggest_model(model_size: str, lang: str | None, on_log=None, why: str = "") -> None:
    """Ngôn ngữ ngoài Trung/Anh mà vẫn chạy model nhỏ thì gợi ý large-v3 (chỉ ghi log)."""
    if not on_log or not lang or lang in STRONG_MEDIUM_LANGS or model_size not in _SMALL_MODELS:
        return
    on_log(f"Gợi ý: {name_vi(lang)} nhận dạng đúng hơn rõ với model large-v3 (phim Thái đo thật: "
           f"phụ đề đúng ý 56 % → 72 % / 108 câu so với medium)." + (f" {why}" if why else "")
           + " Đổi ở “Cấu hình nhận dạng” nếu chữ gốc sai nhiều.")


def _model_on_disk(size: str) -> bool:
    """Model đã tải về máy chưa (không tải, không cần mạng)."""
    try:
        from faster_whisper.utils import download_model

        download_model(size, local_files_only=True, cache_dir=str(MODEL_DIR))
        return True
    except Exception:
        return False


def _upgrade_model(model_size: str, lang: str | None, device: str, on_log=None):
    """medium + ngôn ngữ ngoài Trung/Anh -> nạp large-v3. Trả `(model, "")` hoặc `(None, lý do không đổi)`.

    Chỉ đổi khi chạy GPU (trên CPU large-v3 chậm gấp mấy lần) và model đã có trên máy —
    không tự tải 3,1 GB giữa chừng một job. Nạp hỏng (hết VRAM…) thì giữ medium.
    """
    if not AUTO_UPGRADE or model_size != UPGRADE_FROM or not lang or lang in STRONG_MEDIUM_LANGS:
        return None, ""
    if device != "cuda":
        return None, f"Đang chạy CPU nên app giữ {UPGRADE_FROM} (large-v3 trên CPU chậm hơn nhiều)."
    if not _model_on_disk(UPGRADE_TO):
        return None, f"Máy chưa có model {UPGRADE_TO} (~3,1 GB) — chọn nó ở “Cấu hình nhận dạng” để tải về."
    try:
        model, used = load_model(UPGRADE_TO, "cuda", on_log=on_log, cpu_fallback=False)
    except Exception as exc:
        return None, f"Không nạp được {UPGRADE_TO} trên GPU ({str(exc)[:80]}) nên giữ {UPGRADE_FROM}."
    with _lock:  # nhả VRAM của medium: job này không dùng tới nữa
        for key in [k for k in _cache if k[0] == model_size and k[1] == "cuda"]:
            _cache.pop(key, None)
    if on_log:
        on_log(f"{name_vi(lang)}: tự chuyển sang Whisper `{UPGRADE_TO}` thay cho `{UPGRADE_FROM}` "
               "(phim Thái đo thật: phụ đề đúng ý 56 % → 72 %, khâu nghe lâu hơn ~30 %).")
    return model, ""


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


def load_model(size: str = "medium", device: str = "auto", on_log=None, cpu_fallback: bool = True):
    """Nạp (và cache) model Whisper. device: auto | cuda | cpu

    `cpu_fallback=False`: GPU nạp hỏng thì báo lỗi thay vì lặng lẽ nạp bản CPU.
    """
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
            if device != "cpu" and cpu_fallback:
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


def _word_gaps(segs: list[dict], total: float) -> list[tuple]:
    timed = [w for s in segs for w in (s.get("words") or [s]) if w["end"] > w["start"]]
    return find_gaps(timed, total, min_gap=SPEECH_GAP_MIN)


def _pcm(wav, start: float, end: float):
    import numpy as np

    if (wav.getnchannels(), wav.getsampwidth(), wav.getframerate()) != (1, 2, 16000):
        raise ValueError("Cần WAV mono PCM 16 kHz.")
    pos = min(round(start * 16000), wav.getnframes())
    wav.setpos(pos)
    raw = wav.readframes(max(0, round(end * 16000) - pos))
    return np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0


def _speech_in_gaps(path: str, gaps: list[tuple]) -> list[tuple]:
    """Only examine untranscribed audio, in bounded windows even for feature films."""
    from faster_whisper.vad import VadOptions, get_speech_timestamps

    opts = VadOptions(min_speech_duration_ms=180, min_silence_duration_ms=450,
                      speech_pad_ms=140, max_speech_duration_s=25)
    found = []
    with wave.open(str(path), "rb") as wav:
        for a, b in gaps:
            while a < b:
                end = min(a + 60, b)
                audio = _pcm(wav, a, end)
                if len(audio):
                    for s in get_speech_timestamps(audio, opts):
                        found.append((a + s["start"] / 16000, min(end, a + s["end"] / 16000)))
                a = end
    return found


def _remaining_speech(speech: list[tuple], gaps: list[tuple]) -> list[tuple]:
    remaining = []
    j = 0
    for a, b in speech:
        while j < len(gaps) and gaps[j][1] <= a:
            j += 1
        k = j
        while k < len(gaps) and gaps[k][0] < b:
            lo, hi = max(a, gaps[k][0]), min(b, gaps[k][1])
            if hi - lo >= 0.3:
                remaining.append((round(lo, 3), round(hi, 3)))
            k += 1
    return remaining


# ------------------------------------------------------------------ dò ngôn ngữ


def _read_head(audio_path: str, seconds: float):
    """Mẫu âm thanh 16 kHz mono (float32) của `seconds` giây đầu file.

    File audio.wav của app là PCM 16 bit, 16 kHz, mono (media.extract_audio) nên đọc
    thẳng phần đầu, khỏi giải mã cả phim dài vào RAM; file khác thì nhờ faster-whisper.
    """
    import numpy as np

    sr = 16000
    try:
        with wave.open(audio_path, "rb") as w:
            if w.getframerate() == sr and w.getnchannels() == 1 and w.getsampwidth() == 2:
                raw = w.readframes(int(seconds * sr))
                return np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    except (wave.Error, OSError, EOFError):
        pass
    from faster_whisper.audio import decode_audio

    return decode_audio(audio_path, sampling_rate=sr)[: int(seconds * sr)]


def detect_language(model, audio_path: str) -> tuple[str | None, float]:
    """Dò ngôn ngữ trên các khúc CÓ TIẾNG NGƯỜI thay vì 30 s đầu file.

    Để faster-whisper tự dò thì nó chỉ nghe 30 s đầu (khi tắt VAD); phim mở đầu bằng
    nhạc là đoán bừa, rồi CẢ BÀI bị giải mã bằng ngôn ngữ sai. Đo thật (phim Thái The
    Rules EP5, 30 s đầu là nhạc): tự dò ra "nn" (Na Uy, xác suất 0,20) → câu bịa tiếng
    Anh, chữ Thái lẫn rác La-tinh/Ả Rập, 27/108 câu bị sót. Ở đây: lọc VAD trên 10 phút
    đầu, cộng xác suất ngôn ngữ của tối đa 3 khúc 30 s tiếng người → "th" 0,98, tốn ~3 s;
    bench tiếng Trung vẫn "zh" 1,00.

    Trả (mã, xác suất trung bình), hoặc (None, 0.0) nếu không đủ tiếng người.
    """
    import numpy as np
    from faster_whisper.vad import VadOptions, get_speech_timestamps

    sr = 16000
    head = _read_head(audio_path, LANG_PROBE_SPAN)
    chunks = get_speech_timestamps(head, VadOptions(min_silence_duration_ms=500))
    if sum(c["end"] - c["start"] for c in chunks) < LANG_PROBE_MIN_SPEECH * sr:
        return None, 0.0
    speech = np.concatenate([head[c["start"]:c["end"]] for c in chunks])
    window = 30 * sr
    totals: dict[str, float] = {}
    used = 0
    for k in range(0, min(len(speech), LANG_PROBE_WINDOWS * window), window):
        piece = speech[k:k + window]
        if used and len(piece) < 5 * sr:
            break  # khúc cuối quá ngắn, chỉ làm nhiễu
        _lang, _prob, probs = model.detect_language(audio=piece)
        for code, p in probs:
            totals[code] = totals.get(code, 0.0) + float(p)
        used += 1
    if not totals:
        return None, 0.0
    best = max(totals, key=totals.get)
    return best, totals[best] / used


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
    audio = audio_path
    offset = 0.0
    if clip:
        try:
            with wave.open(str(audio_path), "rb") as wav:
                audio = _pcm(wav, *clip)
            offset = clip[0]
        except (OSError, EOFError, ValueError, wave.Error):
            kwargs["clip_timestamps"] = list(clip)

    segments, info = model.transcribe(audio, **kwargs)

    lo = clip[0] if clip else 0.0
    hi = clip[1] if clip else (total or 0.0)
    span = max(0.1, hi - lo)

    def report(item: dict) -> None:
        if on_progress:
            on_progress(min(1.0, (item["end"] + offset - lo) / span))

    segs = _collect(segments, report)
    if clip:
        for s in segs:
            for timed in [s, *s["words"]]:
                timed["start"] = max(lo, timed["start"] + offset)
                timed["end"] = min(hi, timed["end"] + offset)
            if s["words"]:
                s["words"] = [w for w in s["words"] if w["end"] > w["start"]]
                s["text"] = "".join(w["word"] for w in s["words"]).strip()
        segs = [s for s in segs if s["end"] > s["start"] and s["text"].strip()]
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

    # ------- dò ngôn ngữ trên phần có tiếng người, rồi dùng CHUNG cho mọi lượt.
    # Để None thì mỗi lượt quét bù khoảng trống lại tự dò trên khúc nhạc/ồn của nó
    # (đo thật: ra "Mẹ", "Mبة", "M//" giữa phim Thái).
    lang = language or None
    probe_prob = 0.0
    if not lang:
        try:
            lang, probe_prob = detect_language(model, audio_path)
        except Exception as exc:  # dò hỏng thì để faster-whisper tự dò như trước
            lang, probe_prob = None, 0.0
            if on_log:
                on_log(f"Không dò trước được ngôn ngữ ({exc}) — để Whisper tự dò.")
        if lang and on_log:
            on_log(f"Ngôn ngữ nghe được: {name_vi(lang)} ({lang}, độ tin {probe_prob:.2f}), "
                   "dò trên các khúc có tiếng người."
                   + (" Độ tin thấp — nếu chữ gốc sai, chọn đúng ngôn ngữ nguồn ở bước 1."
                      if probe_prob < 0.5 else ""))

    # ------- ngôn ngữ ngoài Trung/Anh: medium nghe kém hẳn -> đổi model trước lượt 1
    asked_size = model_size
    big, why_not = _upgrade_model(model_size, lang, used_device, on_log)
    if big is not None:
        model, model_size = big, UPGRADE_TO

    # ------- lượt 1
    def p1(x: float) -> None:
        if on_progress:
            on_progress(x * (0.65 if auto_fix else 1.0))

    try:
        segs, info = _one_pass(model, audio_path, lang, vad, initial_prompt, duration, None, p1)
    except Exception as exc:
        if used_device == "cpu" or not _is_cuda_failure(exc):
            raise
        # GPU chào hàng được nhưng chạy không nổi -> làm lại bằng CPU
        if on_log:
            on_log(f"GPU không dùng được: {exc}")
            on_log("Chuyển sang CPU và nhận dạng lại (chậm hơn nhưng vẫn ra kết quả)…")
        _forget_cuda_model(model_size)
        model_size = asked_size  # large-v3 tự đổi là để chạy GPU; trên CPU quay về model đã chọn
        model, used_device = load_model(model_size, "cpu", on_log=on_log)
        segs, info = _one_pass(model, audio_path, lang, vad, initial_prompt, duration, None, p1)

    total = duration or float(getattr(info, "duration", 0.0) or 0.0)
    detected = lang or getattr(info, "language", None)
    # Từ đây mọi lượt dùng đúng ngôn ngữ của lượt 1, kể cả khi lượt 1 phải tự dò.
    lang = detected
    notes: list[str] = []
    segs = _drop_boilerplate(segs, notes, on_log)
    if model_size != UPGRADE_TO:
        _suggest_model(model_size, detected, on_log, why=why_not)

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

        alt, _ = _one_pass(model, audio_path, lang, False, initial_prompt, total, None, p2)
        alt = _drop_boilerplate(alt, [], None)
        holes = find_gaps(segs, total, min_gap=0.18)
        # A longer second pass is not necessarily a superset of the first.
        extra = [s for s in alt if looks_like_speech(s)
                 and any(a <= s["start"] < s["end"] <= b for a, b in holes)]
        if extra:
            segs = sorted(segs + extra, key=lambda s: s["start"])
            cov = coverage(segs, total)
            notes.append(f"bổ sung {len(extra)} đoạn từ lượt không VAD")
            if on_log:
                on_log(f"Giữ lời lượt đầu và bổ sung {len(extra)} đoạn không VAD.")
        elif on_log:
            on_log("Chạy lại không giúp thêm — giữ kết quả ban đầu.")
    elif auto_fix and on_progress:
        on_progress(0.85)

    # ------- lượt 3: quét bù các khoảng trống lớn
    speech = []
    if auto_fix and total > 0:
        holes = _word_gaps(segs, total)
        try:
            speech = _speech_in_gaps(audio_path, holes) if holes else []
            gaps = speech[:GAP_RESCAN_MAX]
        except Exception as exc:
            if on_log:
                on_log(f"Không kiểm tra được tiếng nói bằng VAD ({exc}); quét bù theo khoảng trống.")
            gaps = find_gaps(segs, total)[:GAP_RESCAN_MAX]
        if gaps:
            if on_log:
                pretty = ", ".join(f"{a:.1f}–{b:.1f}s" for a, b in gaps[:5])
                on_log(f"Còn {len(gaps)} khoảng trống ({pretty}"
                       + ("…" if len(gaps) > 5 else "") + ") — đang quét bù…")
            added = 0
            for gi, (a, b) in enumerate(gaps):
                def p3(x: float, gi=gi) -> None:
                    if on_progress:
                        on_progress(0.85 + (gi + x) / len(gaps) * 0.15)

                try:
                    extra, _ = _one_pass(
                        model, audio_path, lang, False, initial_prompt, total, (a, b), p3
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
                on_log("Whisper chưa đọc được thêm lời; không tự điền lời cho đoạn chưa rõ.")

    if on_progress:
        on_progress(1.0)

    # Mỗi từ mang chỉ số đoạn Whisper của nó ("seg"): đoạn Whisper thường là một
    # câu/vế trọn, còn tiếng Trung/Nhật thì không có dấu câu lẫn dấu cách nên
    # subtitles.cues_from_words không còn mốc nào khác để ngắt dòng cho đúng.
    # Đo thật (video 271 dòng thoại): ngắt theo đoạn thì 235 dòng khớp 1 cue,
    # ngắt theo độ dài như trước chỉ 46.
    words: list[dict] = []
    for k, s in enumerate(segs):
        if s["words"]:
            words.extend({**w, "seg": k} for w in s["words"])
        else:
            words.append({"word": s["text"], "start": s["start"], "end": s["end"], "seg": k})
    words.sort(key=lambda w: w["start"])

    voiced = voiced_time(segs)
    if on_log and total:
        on_log(
            f"Kết quả: {len(segs)} đoạn, {voiced:.0f}s có lời trên tổng {total:.0f}s "
            f"(phủ tới {cov * 100:.0f}%)."
        )

    return {
        "language": detected,
        # Ngôn ngữ đưa sẵn cho faster-whisper thì nó báo xác suất 1 — số thật là của lượt dò.
        "language_probability": probe_prob or float(getattr(info, "language_probability", 0.0) or 0.0),
        "duration": total,
        "words": words,
        "segments": [{"start": s["start"], "end": s["end"], "text": s["text"]} for s in segs],
        "device": used_device,
        "model": model_size,
        "coverage": cov,
        "voiced": voiced,
        "notes": notes,
        "speech_gaps": _remaining_speech(speech, _word_gaps(segs, total)),
        "gaps": [(round(a, 1), round(b, 1)) for a, b in find_gaps(segs, total)],
    }
