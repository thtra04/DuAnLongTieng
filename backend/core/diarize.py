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

import importlib.util
import os
import threading
import wave
from importlib.metadata import PackageNotFoundError, version
from inspect import signature
from pathlib import Path
from typing import Callable

from .subtitles import Cue

LEGACY = "pyannote/speaker-diarization-3.1"
COMMUNITY = "pyannote/speaker-diarization-community-1"
SEGMENTATION = "pyannote/segmentation-3.0"
try:
    _legacy_api = version("pyannote.audio").split(".", 1)[0] == "3"
except PackageNotFoundError:
    _legacy_api = False
MODEL_ID = os.environ.get("VSUB_DIARIZE_MODEL") or (LEGACY if _legacy_api else COMMUNITY)

# Cue không chồng lấn lượt nói nào thì tìm lượt gần nhất trong khoảng này (giây).
# Rộng hơn nữa là gán bừa: phụ đề ở đoạn nhạc nền cách chỗ có thoại vài giây thì
# nhãn gán được cũng không đáng tin.
NEAR_WINDOW = 1.5

# Cue phải chồng lấn ít nhất ngần này (tỉ lệ so với độ dài cue) mới nhận nhãn
# chắc chắn. Dưới ngưỡng thì vẫn gán nhưng đánh dấu là "cần xem lại".
CONFIDENT_RATIO = 0.55

_lock = threading.Lock()
_inference_lock = threading.Lock()
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
    state = setup_status(token)
    return state["available"], state["reason"]


def _assets():
    if MODEL_ID == COMMUNITY:
        return [(COMMUNITY, f) for f in ("config.yaml", "embedding/pytorch_model.bin",
                "segmentation/pytorch_model.bin", "plda/plda.npz", "plda/xvec_transform.npz")]
    if MODEL_ID == LEGACY:
        files = [(LEGACY, "config.yaml"), (SEGMENTATION, "pytorch_model.bin"),
                 ("pyannote/wespeaker-voxceleb-resnet34-LM", "pytorch_model.bin")]
        if not _legacy_api:
            files.extend((COMMUNITY, f) for f in ("plda/plda.npz", "plda/xvec_transform.npz"))
        return files
    return []


def _cached_locally() -> bool:
    from huggingface_hub import try_to_load_from_cache

    assets = _assets()
    for repo, filename in assets:
        path = try_to_load_from_cache(repo, filename)
        # Interrupted downloads and Windows/LFS pointer files are not weights.
        if not isinstance(path, str) or Path(path).stat().st_size <= (0 if filename == "config.yaml" else 1024):
            return False
    return bool(assets)


def _valid_input(token) -> bool:
    if token is None:
        return True
    if not isinstance(token, str):
        return False
    text = token.strip()
    return not text or (text.startswith("hf_") and 3 < len(text) <= 512 and not any(c.isspace() for c in text))


def setup_status(token: str = "") -> dict:
    """Local preflight for /api/system: no model import, Hub request or credential in the response."""
    local = Path(MODEL_ID).is_file() or (Path(MODEL_ID) / "config.yaml").is_file()
    pages = [] if local else [MODEL_ID]
    if MODEL_ID == LEGACY:
        pages += [SEGMENTATION] if _legacy_api else [SEGMENTATION, COMMUNITY]
    has_token = bool(hf_token())
    try:
        installed = all(importlib.util.find_spec(mod) is not None for mod in ("pyannote.audio", "torch", "torchaudio"))
    except (ImportError, ValueError):
        installed = False
    state, reason = "configured", ""
    if not installed:
        state, reason = "missing_dependency", "Chưa đủ thư viện pyannote/torch/torchaudio. Cài nhóm diarize trên máy chạy VSub."
    elif not _valid_input(token):
        state, reason = "invalid_token", "Token không đúng định dạng Hugging Face. Hãy dùng token đọc của tài khoản đã được duyệt."
    elif _pipeline is not None and _pipeline_key == (MODEL_ID,):
        state = "loaded"
    elif local:
        state = "local_config"
    else:
        from huggingface_hub.constants import HF_HUB_OFFLINE

        try:
            cached = _cached_locally()
        except (ImportError, OSError, ValueError):
            cached = False
        if cached:
            state = "cached"
        elif HF_HUB_OFFLINE:
            state, reason = "offline", "Máy chủ đang ở chế độ offline và chưa có đủ tệp model. Tải model trước hoặc dùng cách không cần token."
        elif not (has_token or token and token.strip()):
            state, reason = "needs_token", "Chưa đủ tệp model trên máy. Cần token có quyền đọc để tải lần đầu."
    return {"available": state in ("configured", "loaded", "cached", "local_config"), "state": state,
            "reason": reason, "has_token": has_token, "model": Path(MODEL_ID).name if local else MODEL_ID,
            "model_pages": pages}


def check_access(token: str = "") -> tuple[bool, str]:
    """Only on request: HEAD the configured repositories; no audio, download or inference."""
    status = setup_status(token)
    if not status["available"]:
        return False, status["reason"]
    if status["state"] != "configured":
        return True, {"loaded": "Model đã nạp; không cần token.", "cached": "Đủ tệp trong cache; không cần token.",
                      "local_config": "Đã thấy cấu hình cục bộ; trọng số sẽ được kiểm tra khi nạp."}[status["state"]]
    from huggingface_hub import get_hf_file_metadata, hf_hub_url

    for repo in status["model_pages"]:
        filename = next((f for r, f in _assets() if r == repo), "config.yaml")
        try:
            url = hf_hub_url(repo, filename, endpoint="https://huggingface.co")
            get_hf_file_metadata(url, token=hf_token(token), timeout=5)
        except Exception as exc:
            return False, _explain_load_error(exc, repo)
    return True, "Có quyền đọc model. Chưa tải trọng số; lần phân tích đầu tiên cần Internet."


# ------------------------------------------------------------------ nạp model


def _load(token: str = "", on_log: Callable[[str], None] | None = None):
    global _pipeline, _pipeline_key

    key = (MODEL_ID,)
    with _lock:
        if _pipeline is not None and _pipeline_key == key:
            return _pipeline

        # Phải đặt TRƯỚC dòng import: pyannote đọc biến này lúc nạp module và
        # mặc định gửi thời lượng audio của người dùng về otel.pyannote.ai.
        # config.py đã đặt rồi; lặp lại ở đây để không phụ thuộc thứ tự import.
        os.environ.setdefault("PYANNOTE_METRICS_ENABLED", "false")

        auth = hf_token(token) or None
        if on_log:
            on_log("Đang nạp model phân đoạn người nói…")
        try:
            from huggingface_hub.constants import HF_HUB_CACHE
            from pyannote.audio import Pipeline

            auth_arg = "use_auth_token" if "use_auth_token" in signature(Pipeline.from_pretrained).parameters else "token"
            source = MODEL_ID
            if MODEL_ID == COMMUNITY and _cached_locally():
                from huggingface_hub import try_to_load_from_cache

                source = str(Path(try_to_load_from_cache(MODEL_ID, "config.yaml")).parent)
            pipeline = Pipeline.from_pretrained(source, cache_dir=HF_HUB_CACHE, **{auth_arg: auth})
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


def _explain_load_error(exc: Exception, repo: str | None = None) -> str:
    low = f"{type(exc).__name__} {exc}".lower()
    if any(s in low for s in ("401", "403", "unauthorized", "forbidden", "gated", "awaiting")):
        return (
            f"Chưa có quyền đọc {repo or MODEL_ID}. Chấp nhận điều khoản của model "
            "và dùng token đọc từ đúng tài khoản (fine-grained cần quyền đọc model gated)."
        )
    if any(s in low for s in ("connection", "timeout", "offline", "resolve")):
        return "Không kết nối được Hugging Face. Kiểm tra mạng/chế độ offline hoặc dùng tách vai không token."
    if any(s in low for s in ("import", "dll", "torchcodec")):
        return "Không nạp được thư viện âm thanh. Kiểm tra bộ torch, torchaudio và FFmpeg của máy chủ."
    # Raw Hub exceptions can contain request details. They must not enter job logs or HTTP responses.
    return f"Không nạp được model phân đoạn ({type(exc).__name__}). Kiểm tra bản pyannote và các tệp model."


# ------------------------------------------------------------------ chạy


def _pcm_audio(wav_path: str | Path) -> dict:
    """Feed the PCM produced by media.extract_audio directly; no TorchCodec DLL is needed."""
    import numpy as np
    import torch

    path = Path(wav_path)
    with wave.open(str(path), "rb") as wav:
        frames, rate = wav.getnframes(), wav.getframerate()
        if (wav.getnchannels() != 1 or wav.getsampwidth() != 2 or frames < 1
                or frames > path.stat().st_size // 2):
            raise DiarizeError("Đường tiếng không phải WAV PCM 16-bit mono hợp lệ. Hãy tách lại âm thanh.")
        # One float buffer for the model; don't duplicate an entire film in memory as PCM bytes.
        audio = np.empty(frames, dtype=np.float32)
        for start in range(0, frames, 262144):
            stop = min(start + 262144, frames)
            pcm = np.frombuffer(wav.readframes(stop - start), dtype="<i2")
            if pcm.size != stop - start:
                raise DiarizeError("File âm thanh bị thiếu dữ liệu. Hãy tách lại âm thanh.")
            np.multiply(pcm, 1 / 32768., out=audio[start:stop])
    return {"waveform": torch.from_numpy(audio).unsqueeze(0), "sample_rate": rate}


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
        if hook:
            kwargs["hook"] = hook
        with _inference_lock:
            annotation = pipeline(_pcm_audio(wav_path), **kwargs)
    except DiarizeError:
        raise
    except Exception as exc:
        raise DiarizeError(f"Phân đoạn người nói thất bại ({type(exc).__name__}). Kiểm tra đường tiếng và bộ nhớ máy chủ.") from exc

    # pyannote 4 may return DiarizeOutput rather than an Annotation directly.
    annotation = getattr(annotation, "exclusive_speaker_diarization", None) or getattr(
        annotation, "speaker_diarization", annotation)
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
    """Translate pyannote batch callbacks to monotonic progress in the Studio, not a console bar."""
    if on_progress is None:
        return None
    spans = {"segmentation": (0, .45), "embeddings": (.45, .92), "discrete_diarization": (.92, .98)}
    previous = -1.

    def hook(step_name, step_artifact=None, file=None, total=None, completed=None):
        nonlocal previous
        if step_name not in spans:
            return
        start, end = spans[step_name]
        ratio = min(1., max(0., completed / total)) if total and completed is not None else 1.
        progress = start + (end - start) * ratio
        if progress > previous:
            on_progress(progress)
            previous = progress

    return hook


def relabel_by_talktime(turns: list[dict]) -> list[dict]:
    """Đổi `SPEAKER_00`… thành `S1`, `S2`… theo tổng thời gian nói giảm dần."""
    talk: dict[str, float] = {}
    for t in turns:
        talk[t["speaker"]] = talk.get(t["speaker"], 0.0) + (t["end"] - t["start"])
    order = sorted(talk, key=lambda s: (-talk[s], s))
    mapping = {old: f"S{i}" for i, old in enumerate(order, 1)}
    return [{**t, "speaker": mapping[t["speaker"]]} for t in turns]


# ------------------------------------------------------------------ gán nhãn


def _split_spoken_cue(cue: Cue, turns: list[dict]) -> list[Cue]:
    """Split only at timed words with unambiguous evidence for a different voice."""
    if cue.pinned or cue.speaker_fixed or cue.text2 or len(cue.words) < 2 or len({t["speaker"] for t in turns}) < 2:
        return [cue]
    cuts = [0]
    last = ""
    for i, w in enumerate(cue.words):
        a, b = w["start"], w["end"]
        if b <= a:
            continue
        roles = {t["speaker"] for t in turns
                 if min(t["end"], b) - max(t["start"], a) >= (b - a) * CONFIDENT_RATIO}
        if len(roles) == 1:
            who = next(iter(roles))
            if last and who != last and a > max(cue.start, cue.words[cuts[-1]]["start"]) and a < cue.end:
                cuts.append(i)
            last = who
    if len(cuts) == 1:
        return [cue]
    parts = []
    for i, j in zip(cuts, cuts[1:] + [len(cue.words)]):
        words = cue.words[i:j]
        start = max(cue.start, words[0]["start"]) if i else cue.start
        end = min(cue.end, cue.words[j]["start"], words[-1]["end"]) if j < len(cue.words) else cue.end
        if end <= start:
            return [cue]
        parts.append(Cue(start, end, "".join(w["word"] for w in words).strip(), words=words))
    return parts


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
    stats = {"total": len(cues), "labeled": 0, "unsure": 0, "empty": 0, "speakers": 0, "review_at": []}
    if not cues:
        return stats
    if not turns:
        for cue in cues:
            if not cue.speaker_fixed:
                cue.speaker = ""
        stats["labeled"] = sum(bool(c.speaker) for c in cues)
        stats["empty"] = len(cues) - stats["labeled"]
        stats["speakers"] = len({c.speaker for c in cues if c.speaker})
        return stats

    pieces = []
    for cue in cues:
        local = []
        for turn in turns:
            if turn["start"] >= cue.end:
                break
            if turn["end"] > cue.start:
                local.append(turn)
        pieces.extend((part, local) for part in _split_spoken_cue(cue, local))
    cues[:] = [part for part, _ in pieces]
    stats["total"] = len(cues)
    for cue, local in pieces:
        if cue.speaker_fixed:
            stats["labeled" if cue.speaker else "empty"] += 1
            continue
        overlap = {}
        for turn in local:
            gap = min(cue.end, turn["end"]) - max(cue.start, turn["start"])
            if gap > 0:
                who = turn["speaker"]
                overlap[who] = overlap.get(who, 0.0) + gap
        best = max(overlap, key=overlap.get) if overlap else ""
        best_overlap = overlap.get(best, 0.0)

        if not best:
            best = _nearest(cue, turns)
            if best:
                stats["labeled"] += 1
                stats["unsure"] += 1
                if len(stats["review_at"]) < 6:
                    stats["review_at"].append(cue.start)
            else:
                stats["empty"] += 1
            cue.speaker = best
            continue

        span = max(0.01, cue.end - cue.start)
        if best_overlap / max(span, sum(overlap.values())) < CONFIDENT_RATIO:
            stats["unsure"] += 1
            if len(stats["review_at"]) < 6:
                stats["review_at"].append(cue.start)
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
