"""Phân đoạn người nói (speaker diarization) bằng pyannote.audio.

Trả lời câu hỏi "đoạn nào là ai nói", để mỗi nhân vật trong phim được lồng một
giọng riêng thay vì cả phim đọc bằng một giọng duy nhất.

Luồng::

    audio.wav  ->  pyannote  ->  các lượt nói (start, end, speaker)
                                        |
                              gán vào cue theo độ chồng lấn lớn nhất
                                        |
                                 cue.speaker = "S1" | "S2" | ...

Nhãn của pyannote là `SPEAKER_00`, `SPEAKER_01`… theo thứ tự nó gặp. Ở đây ta
đánh số lại theo **tổng thời gian nói giảm dần**, nên `S1` luôn là người nói
nhiều nhất — thường là vai chính. Nhờ vậy thứ tự nhân vật ổn định giữa các lần
chạy, và người dùng thấy vai chính ở đầu danh sách thay vì thứ tự ngẫu nhiên.

Module này không phụ thuộc ngôn ngữ: nó chỉ đọc đặc trưng âm học của giọng.
"""

from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Callable

from .config import MODEL_DIR
from .subtitles import Cue

# Model mặc định. Cần chấp nhận điều khoản trên trang model rồi mới tải được.
MODEL_ID = os.environ.get("VSUB_DIARIZE_MODEL", "pyannote/speaker-diarization-3.1")

# Cue không chồng lấn lượt nói nào thì tìm lượt gần nhất trong khoảng này (giây).
# Rộng hơn nữa là gán bừa: phụ đề ở đoạn nhạc nền cách chỗ có thoại vài giây thì
# nhãn gán được cũng không đáng tin.
NEAR_WINDOW = 1.5

# Cue phải chồng lấn ít nhất ngần này (tỉ lệ so với độ dài cue) mới nhận nhãn
# chắc chắn. Dưới ngưỡng thì vẫn gán nhưng đánh dấu là "cần xem lại".
CONFIDENT_RATIO = 0.55

_lock = threading.Lock()
_pipeline = None
_pipeline_key: tuple | None = None


class DiarizeError(RuntimeError):
    pass


# ------------------------------------------------------------------ sẵn sàng?


def hf_token(explicit: str = "") -> str:
    """Token Hugging Face để tải model. Ưu tiên token người dùng nhập."""
    if explicit and explicit.strip():
        return explicit.strip()
    for name in ("HF_TOKEN", "HUGGINGFACE_TOKEN", "HUGGING_FACE_HUB_TOKEN"):
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return ""


def available(token: str = "") -> tuple[bool, str]:
    """Có chạy được diarization không, kèm lý do nếu không.

    Cố ý KHÔNG tải model, và cũng KHÔNG `import` thư viện thật ở đây — hàm này
    chạy mỗi lần mở trang qua `/api/system`. `import pyannote.audio` kéo theo cả
    torch và speechbrain, mất hàng chục giây lượt đầu; `find_spec` chỉ tra xem
    gói có tồn tại hay không nên gần như tức thì. (Cùng lý do mà `/api/system`
    không kiểm torch cho tính năng nhân bản giọng — xem `tts_voices` ở main.py.)
    """
    import importlib.util

    try:
        if importlib.util.find_spec("pyannote.audio") is None:
            return False, "Chưa cài pyannote: uv sync --extra diarize"
        if importlib.util.find_spec("torch") is None:
            return False, "Nhận diện người nói cần `torch`: uv sync --extra diarize"
    except (ImportError, ValueError) as exc:
        return False, f"Không kiểm được thư viện pyannote: {exc}"

    if not hf_token(token) and not _cached_locally():
        return False, (
            "Cần token Hugging Face để tải model phân đoạn người nói. "
            "Vào trang model, bấm chấp nhận điều khoản, rồi dán token vào ô "
            "bên dưới (hoặc đặt biến môi trường HF_TOKEN)."
        )
    return True, ""


def _cached_locally() -> bool:
    """Model đã tải về máy rồi thì không cần token nữa."""
    for base in (MODEL_DIR, Path.home() / ".cache" / "huggingface" / "hub"):
        try:
            slug = "models--" + MODEL_ID.replace("/", "--")
            if (Path(base) / slug).is_dir():
                return True
        except OSError:
            continue
    return False


# ------------------------------------------------------------------ nạp model


def _load(token: str = "", on_log: Callable[[str], None] | None = None):
    global _pipeline, _pipeline_key

    key = (MODEL_ID,)
    with _lock:
        if _pipeline is not None and _pipeline_key == key:
            return _pipeline

        from pyannote.audio import Pipeline

        auth = hf_token(token) or None
        if on_log:
            on_log("Đang nạp model phân đoạn người nói (lần đầu tải ~1 GB)…")
        try:
            pipeline = Pipeline.from_pretrained(MODEL_ID, use_auth_token=auth)
        except Exception as exc:
            raise DiarizeError(_explain_load_error(exc)) from exc
        if pipeline is None:
            # from_pretrained trả None (không raise) khi token sai hoặc chưa
            # chấp nhận điều khoản — thông báo mặc định sẽ rất khó hiểu.
            raise DiarizeError(
                f"Không tải được `{MODEL_ID}`. Hãy mở trang model trên Hugging Face, "
                "bấm chấp nhận điều khoản bằng chính tài khoản của token, rồi thử lại."
            )

        pipeline = _to_gpu(pipeline, on_log)
        _pipeline, _pipeline_key = pipeline, key
        return pipeline


def _to_gpu(pipeline, on_log=None):
    """Đẩy pipeline lên GPU nếu có. Lỗi thì ở lại CPU, không làm hỏng cả job."""
    try:
        import torch

        if not torch.cuda.is_available():
            if on_log:
                on_log("Phân đoạn người nói chạy trên CPU (chậm hơn ~5 lần).")
            return pipeline
        pipeline.to(torch.device("cuda"))
        if on_log:
            on_log("Phân đoạn người nói chạy trên GPU.")
    except Exception as exc:
        if on_log:
            on_log(f"Không dùng được GPU cho phân đoạn người nói ({exc}) — dùng CPU.")
    return pipeline


def _explain_load_error(exc: Exception) -> str:
    msg = str(exc)
    low = msg.lower()
    if "401" in msg or "unauthorized" in low or "gated" in low or "awaiting" in low:
        return (
            f"Chưa có quyền tải `{MODEL_ID}`. Mở trang model trên Hugging Face, "
            "bấm chấp nhận điều khoản, rồi dùng token của chính tài khoản đó."
        )
    if "connection" in low or "timeout" in low or "resolve" in low:
        return "Không kết nối được Hugging Face để tải model. Kiểm tra mạng rồi thử lại."
    return f"Không nạp được model phân đoạn người nói: {msg}"


# ------------------------------------------------------------------ chạy


def run(
    wav_path: str | Path,
    num_speakers: int | None = None,
    min_speakers: int | None = None,
    max_speakers: int | None = None,
    token: str = "",
    on_log: Callable[[str], None] | None = None,
    on_progress: Callable[[float], None] | None = None,
) -> list[dict]:
    """Phân đoạn người nói trên một file wav.

    Trả về danh sách lượt nói ``[{"start", "end", "speaker"}]``, đã sắp theo
    thời gian và đánh số lại theo tổng thời gian nói giảm dần.

    Biết trước số nhân vật thì truyền `num_speakers` — kết quả tốt hơn hẳn so
    với để model tự đoán, nhất là ở cảnh chỉ có hai người đối thoại.
    """
    pipeline = _load(token, on_log)

    kwargs: dict = {}
    if num_speakers and num_speakers > 0:
        kwargs["num_speakers"] = int(num_speakers)
    else:
        if min_speakers and min_speakers > 0:
            kwargs["min_speakers"] = int(min_speakers)
        if max_speakers and max_speakers > 0:
            kwargs["max_speakers"] = int(max_speakers)

    hook = _progress_hook(on_progress)
    try:
        if hook is not None:
            with hook as h:
                annotation = pipeline(str(wav_path), hook=h, **kwargs)
        else:
            annotation = pipeline(str(wav_path), **kwargs)
    except Exception as exc:
        raise DiarizeError(f"Phân đoạn người nói thất bại: {exc}") from exc

    turns = [
        {"start": float(seg.start), "end": float(seg.end), "speaker": str(label)}
        for seg, _, label in annotation.itertracks(yield_label=True)
        if float(seg.end) > float(seg.start)
    ]
    turns.sort(key=lambda t: (t["start"], t["end"]))
    turns = relabel_by_talktime(turns)

    if on_progress:
        on_progress(1.0)
    if on_log:
        on_log(
            f"Nghe ra {len(set(t['speaker'] for t in turns))} người nói "
            f"trong {len(turns)} lượt thoại."
        )
    return turns


def _progress_hook(on_progress):
    """ProgressHook của pyannote, nếu bản đang cài có. Không có thì bỏ qua."""
    if on_progress is None:
        return None
    try:
        from pyannote.audio.pipelines.utils.hook import ProgressHook
    except Exception:
        return None
    try:
        return ProgressHook()
    except Exception:
        return None


def relabel_by_talktime(turns: list[dict]) -> list[dict]:
    """Đổi `SPEAKER_00`… thành `S1`, `S2`… theo tổng thời gian nói giảm dần."""
    talk: dict[str, float] = {}
    for t in turns:
        talk[t["speaker"]] = talk.get(t["speaker"], 0.0) + (t["end"] - t["start"])
    order = sorted(talk, key=lambda s: (-talk[s], s))
    mapping = {old: f"S{i}" for i, old in enumerate(order, 1)}
    return [{**t, "speaker": mapping[t["speaker"]]} for t in turns]


# ------------------------------------------------------------------ gán nhãn


def assign(cues: list[Cue], turns: list[dict]) -> dict:
    """Gán nhãn nhân vật cho từng cue theo **độ chồng lấn thời gian lớn nhất**.

    Sửa `cues` tại chỗ. Trả về thống kê để pipeline ghi log.

    Ba ca khó, xử lý như sau:

    * **Cue vắt qua hai người.** Lấy người chồng lấn nhiều hơn. Nếu phần chồng
      lấn thắng chưa quá `CONFIDENT_RATIO` độ dài cue thì đếm vào `unsure` để
      nhắc người dùng xem lại — chứ không bỏ trống, vì bỏ trống thì cue đó
      không được lồng tiếng.
    * **Cue không chồng lấn lượt nào** (thường là phụ đề trên nền nhạc). Tìm
      lượt gần nhất trong `NEAR_WINDOW` giây; xa hơn thì để trống.
    * **Tiếng nói chồng lấn.** pyannote trả nhiều lượt cùng lúc; công thức
      chồng lấn lớn nhất vẫn chọn được người nói chính của cue đó.
    """
    stats = {"total": len(cues), "labeled": 0, "unsure": 0, "empty": 0, "speakers": 0}
    if not cues:
        return stats
    if not turns:
        for cue in cues:
            cue.speaker = ""
        stats["empty"] = len(cues)
        return stats

    for cue in cues:
        best, best_overlap = "", 0.0
        for turn in turns:
            if turn["start"] >= cue.end:
                break  # turns đã sắp theo start -> phía sau không thể chồng lấn
            gap = min(cue.end, turn["end"]) - max(cue.start, turn["start"])
            if gap > best_overlap:
                best, best_overlap = turn["speaker"], gap

        if not best:
            best = _nearest(cue, turns)
            if best:
                stats["labeled"] += 1
                stats["unsure"] += 1
            else:
                stats["empty"] += 1
            cue.speaker = best
            continue

        span = max(0.01, cue.end - cue.start)
        if best_overlap / span < CONFIDENT_RATIO:
            stats["unsure"] += 1
        stats["labeled"] += 1
        cue.speaker = best

    stats["speakers"] = len({c.speaker for c in cues if c.speaker})
    return stats


def _nearest(cue: Cue, turns: list[dict]) -> str:
    """Lượt nói gần cue nhất trong `NEAR_WINDOW` giây, hoặc "" nếu quá xa."""
    best, best_dist = "", NEAR_WINDOW
    for turn in turns:
        if turn["end"] < cue.start:
            dist = cue.start - turn["end"]
        elif turn["start"] > cue.end:
            dist = turn["start"] - cue.end
        else:
            return turn["speaker"]  # thực ra có chồng lấn
        if dist < best_dist:
            best, best_dist = turn["speaker"], dist
    return best


# ------------------------------------------------------------------ tổng hợp


def speakers_of(cues: list[Cue]) -> list[dict]:
    """Danh sách nhân vật rút từ cue đã gán nhãn, để giao diện dựng bảng giọng.

    Mỗi mục: ``{id, lines, seconds, first_line, sample}``. Sắp theo số giây nói
    giảm dần, cùng thứ tự với nhãn `S1`, `S2`… nên `S1` luôn đứng đầu.
    """
    table: dict[str, dict] = {}
    for i, cue in enumerate(cues):
        sid = (cue.speaker or "").strip()
        if not sid:
            continue
        item = table.setdefault(
            sid,
            {"id": sid, "lines": 0, "seconds": 0.0, "first_line": i + 1, "sample": ""},
        )
        item["lines"] += 1
        item["seconds"] += max(0.0, cue.end - cue.start)
        if not item["sample"]:
            text = (cue.text2 or cue.text or "").strip()
            if text:
                item["sample"] = text[:70]

    out = sorted(table.values(), key=lambda s: -s["seconds"])
    for item in out:
        item["seconds"] = round(item["seconds"], 1)
    return out
