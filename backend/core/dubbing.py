"""Lồng tiếng (dubbing) bằng VieNeu-TTS.

Luồng: mỗi cue -> TTS ra audio -> ép vừa khung thời gian của cue -> ghép thành
một track hoàn chỉnh -> trộn với tiếng gốc -> mux vào video.

Repo TTS: https://github.com/pnnbao97/VieNeu-TTS (Apache-2.0)
"""

from __future__ import annotations

import math
import re
import subprocess
import sys
import threading
import wave
from pathlib import Path
from typing import Callable

from . import media
from .subtitles import Cue

SR = 48000  # VieNeu-TTS v3 Turbo xuất 48 kHz

STYLES = [
    {"id": "tu_nhien", "label": "Tự nhiên (hội thoại)"},
    {"id": "tin_tuc", "label": "Bản tin"},
    {"id": "doc_truyen", "label": "Đọc truyện"},
]

CLONE_VOICE = "__clone__"  # giá trị đặc biệt: nhân bản giọng trong video

_lock = threading.Lock()
_engine = None


class DubError(RuntimeError):
    pass


# --------------------------------------------------------------- engine


def available(deep: bool = False) -> tuple[bool, str]:
    """VieNeu-TTS dùng được chưa.

    `deep=False` (mặc định) chỉ tra xem gói có tồn tại không — `/api/system` gọi
    hàm này mỗi lần mở trang, mà `import vieneu` kéo theo onnxruntime mất mấy
    giây. `deep=True` nạp thật, dùng ở `/api/tts/voices` — chỗ đó vốn đã phải
    chờ nạp model nên thêm vài giây không ai để ý, và đổi lại thì lỗi kiểu
    "thiếu DLL onnxruntime" được báo đúng tên thay vì im lặng.
    """
    if not deep:
        import importlib.util

        try:
            if importlib.util.find_spec("vieneu") is None:
                return False, "Chưa cài VieNeu-TTS: uv sync --extra tts"
        except (ImportError, ValueError):
            return False, "Chưa cài VieNeu-TTS: uv sync --extra tts"
        return True, ""

    try:
        import vieneu  # noqa: F401

        return True, ""
    except ImportError:
        return False, "Chưa cài VieNeu-TTS: uv sync --extra tts"
    except Exception as exc:  # lỗi import khác (thiếu onnxruntime…)
        return False, f"VieNeu-TTS lỗi khi nạp: {exc}"


def clone_available() -> tuple[bool, str]:
    """Nhân bản giọng cần torch + torchaudio.

    Giọng có sẵn thì không cần: VieNeu-TTS v3 Turbo đọc bằng onnxruntime. Nhưng
    lúc nhân bản, nó gọi `prepare_reference()` để rút đặc trưng từ đoạn mẫu —
    chỗ đó mới cần torch. Đây là lý do phải tách thành nhóm `clone` riêng: kéo
    torch về chỉ vì tính năng này thì tốn thêm mấy GB.
    """
    ok, reason = available()
    if not ok:
        return False, reason
    missing = []
    for mod in ("torch", "torchaudio"):
        try:
            __import__(mod)
        except ImportError:
            missing.append(mod)
    if missing:
        return False, (
            f"Nhân bản giọng cần thêm {' và '.join('`' + m + '`' for m in missing)}. "
            "Chạy: uv sync --extra clone (hoặc chọn một giọng có sẵn thay thế)."
        )
    return True, ""


def get_engine():
    global _engine
    with _lock:
        if _engine is not None:
            return _engine
        ok, reason = available()
        if not ok:
            raise DubError(reason)
        from vieneu import Vieneu  # type: ignore

        _engine = Vieneu()
        return _engine


def list_voices() -> list[dict]:
    """Danh sách giọng đọc có sẵn. Trả về [] nếu chưa cài TTS."""
    ok, _ = available()
    if not ok:
        return []
    try:
        raw = get_engine().list_preset_voices()
    except Exception:
        return []

    voices: list[dict] = []
    for item in raw or []:
        if isinstance(item, (tuple, list)) and len(item) >= 2:
            label, vid = str(item[0]), str(item[1])
        else:
            label = vid = str(item)
        voices.append({"id": vid, "label": label})
    return voices


# ------------------------------------------------------------- WAV I/O


# Ghi/đọc wav theo khối thay vì cả file một lượt. Track lồng tiếng của một tập
# 9 tiếng là mảng float32 ~5.9 GB; nếu clip/đổi kiểu/tobytes trên cả mảng thì
# giữ đồng thời 2 bản float32 + 2 bản int16 = ~17.8 GB. Chia khối 30 giây thì
# đỉnh chỉ hơn chính mảng gốc vài MB.
_IO_CHUNK = 30 * SR


def _write_wav(path: Path, samples, sr: int = SR) -> Path:
    import numpy as np

    data = np.asarray(samples, dtype=np.float32).reshape(-1)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        for start in range(0, data.size, _IO_CHUNK):
            block = np.clip(data[start:start + _IO_CHUNK], -1.0, 1.0)
            wf.writeframes((block * 32767.0).astype("<i2").tobytes())
    return path


def _read_wav(path: Path):
    import numpy as np

    with wave.open(str(path), "rb") as wf:
        total, channels, sr = wf.getnframes(), wf.getnchannels(), wf.getframerate()
        out = np.empty(total * channels, dtype=np.float32)
        at = 0
        while at < out.size:
            raw = wf.readframes(_IO_CHUNK)
            if not raw:
                break
            block = np.frombuffer(raw, dtype="<i2")
            out[at:at + block.size] = block
            at += block.size
    out = out[:at]
    out /= 32768.0
    if channels > 1:
        out = out.reshape(-1, channels).mean(axis=1)
    return out, sr


# ---------------------------------------------------- ép vừa khung giờ


def _atempo_chain(factor: float) -> str:
    """atempo chỉ nhận 0.5–2.0 mỗi tầng, nối nhiều tầng cho hệ số lớn."""
    parts: list[str] = []
    remaining = factor
    while remaining > 2.0:
        parts.append("atempo=2.0")
        remaining /= 2.0
    while remaining < 0.5:
        parts.append("atempo=0.5")
        remaining /= 0.5
    parts.append(f"atempo={remaining:.5f}")
    return ",".join(parts)


def _time_stretch(samples, factor: float, tmpdir: Path, tag: str):
    """Tăng/giảm tốc audio mà giữ nguyên cao độ (ffmpeg atempo)."""
    if abs(factor - 1.0) < 0.02:
        return samples
    src = tmpdir / f"s{tag}.wav"
    dst = tmpdir / f"d{tag}.wav"
    _write_wav(src, samples)
    cmd = [
        media.ffmpeg_exe(), "-hide_banner", "-nostdin", "-y", "-loglevel", "error",
        "-i", str(src), "-filter:a", _atempo_chain(factor),
        "-ar", str(SR), "-ac", "1", "-c:a", "pcm_s16le", str(dst),
    ]
    proc = subprocess.run(
        cmd, capture_output=True, text=True, errors="ignore",
        creationflags=(0x08000000 if sys.platform == "win32" else 0),
    )
    if proc.returncode != 0 or not dst.exists():
        return samples  # không ép được thì giữ nguyên
    out, _ = _read_wav(dst)
    src.unlink(missing_ok=True)
    dst.unlink(missing_ok=True)
    return out


# Cho câu vào sớm tối đa bao nhiêu giây khi khung không đủ. Vào sớm khó nhận ra
# hơn nhiều so với tràn qua câu sau — tràn thì dồn lệch cho tất cả câu tiếp theo.
MAX_LEAD_IN = 0.15
# Một đơn vị đọc không dài quá bao nhiêu giây / bao nhiêu ký tự.
#
# Đo trên video thật (69 cue / 392s), số câu phải tăng tốc theo mức chặn:
#     không chặn (15 đơn vị)  ->  8 câu, nén tối đa 1.24x
#     chặn 20s   (31 đơn vị)  -> 18 câu, nén tối đa 1.42x
#     chặn 14s   (43 đơn vị)  -> 24 câu, nén tối đa 1.41x
#     từng cue   (69 đơn vị)  -> 43 câu, nén tối đa 1.44x
# Giọng bị nén nghe gấp và máy móc — đó là khuyết điểm dễ nghe nhất — nên chặn
# càng ít càng tốt. `translate.group_cues` đã giới hạn 6 cue mỗi nhóm nên không
# có khối nào quá to; hai hằng số này chỉ để bắt ca bất thường.
MAX_UNIT_SPAN = 30.0
MAX_UNIT_CHARS = 900
# Ngưỡng coi là im lặng khi cắt đầu/cuối clip TTS (tỉ lệ so với đỉnh của clip)
_SILENCE_GATE = 0.015


def _trim_silence(audio, keep: float = 0.02):
    """Cắt lặng đầu/cuối clip TTS. Trả về (audio đã cắt, số giây đã cắt).

    Giữ lại `keep` giây ở hai đầu cho khỏi cụt phụ âm bật (p, t, k).
    """
    import numpy as np

    a = np.abs(audio)
    peak = float(a.max()) if a.size else 0.0
    if peak <= 1e-6:
        return audio, 0.0
    hits = np.flatnonzero(a > peak * _SILENCE_GATE)
    if not hits.size:
        return audio, 0.0
    pad = int(keep * SR)
    lo = max(0, int(hits[0]) - pad)
    hi = min(a.size, int(hits[-1]) + pad + 1)
    if hi - lo >= a.size:
        return audio, 0.0
    return audio[lo:hi], (a.size - (hi - lo)) / SR


_CUE_TAG = re.compile(r"\[[^\]]{1,20}\]")


# Chữ mà giọng đọc tiếng Việt phát âm được. Không có ký tự nào thuộc nhóm này
# thì đưa vào TTS là vô nghĩa.
_READABLE = re.compile(r"[0-9A-Za-zÀ-ỹ]")


def _clean_for_tts(text: str, add_stop: bool = True) -> str:
    """Bỏ xuống dòng, ký tự lạ; giữ lại cue cảm xúc dạng [cười].

    Trả về chuỗi rỗng nếu chẳng còn gì đọc được. Bỏ bước này thì những cue chỉ
    có dấu câu hay chữ Hán vẫn được đưa vào TTS, và model **sinh chạy loạn**:
    đo thật, "..." ra 2,16 giây, "第一集" (3 ký tự) ra 2,08 giây, có lần chạm
    đúng trần 24 giây — rồi đổ vào track, đè lên mấy câu thoại thật phía sau,
    mà vẫn bị đếm là đọc thành công.

    `add_stop=False` khi text chỉ là **một mảnh giữa câu** sắp được nối với mảnh
    khác. Đây là chỗ từng sai: mảnh nào cũng bị chấm câu trước khi nối, nên
    "Hôm nay" + "trời đẹp." ra "Hôm nay. trời đẹp." — TTS đọc thành hai câu, tụt
    giọng và nghỉ ngay giữa câu, đúng cái mà `speech_units` sinh ra để tránh.
    """
    text = text.replace("\n", " ").replace("♪", " ")
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    if not _READABLE.search(text):
        return ""
    if add_stop and text and text[-1] not in ".!?…,;:":
        text += "."
    return text


def _runaway(audio_seconds: float, text: str) -> bool:
    """Clip có dài bất thường so với số chữ không.

    TTS đôi khi không gặp điểm kết thúc và sinh tới trần (24 giây). Giọng thật
    đọc ~22 ký tự/giây; lấy 11 ký tự/giây + 1,5 giây làm mức khoan dung, câu
    tiếng Việt ngắn thật ("Dạ.", "Cứu tôi!") đo được 0,64–1,28 giây nên không
    bị bắt oan.
    """
    return audio_seconds > len(text) / 11.0 + 1.5


# ------------------------------------------------------------ pipeline


# Nhãn âm thanh / lời nhạc — không phải thoại, đừng lấy làm mẫu giọng
_NOT_SPEECH = re.compile(r"^[\s♪♫\[\](){}（）【】《》\-—…]*$|^[\[(（【].{0,30}[\])）】]$")


def _score_reference(video: Path, cue: Cue, tmp: Path, min_len: float) -> tuple[float, float]:
    """Cắt thử một cue rồi cho điểm: (tỉ lệ khung có tiếng, mức dBFS)."""
    length = min(8.0, max(min_len, cue.end - cue.start))
    try:
        media.run_ffmpeg_progress(
            [
                "-ss", f"{cue.start:.2f}", "-t", f"{length:.2f}",
                "-i", str(Path(video).resolve()),
                "-vn", "-ac", "1", "-ar", "24000", "-c:a", "pcm_s16le",
                str(tmp.resolve()),
            ],
            0.0,
        )
    except Exception:
        return 0.0, -99.0
    if not tmp.exists():
        return 0.0, -99.0

    import numpy as np

    samples, sr = _read_wav(tmp)
    data = np.abs(np.asarray(samples, dtype=np.float32).reshape(-1))
    if not data.size:
        return 0.0, -99.0
    peak = float(data.max())
    if peak <= 1e-5:
        return 0.0, -99.0
    step = max(1, int(sr * 0.02))
    n = data.size // step
    frames = data[: n * step].reshape(n, step).max(axis=1)
    voiced = float((frames > peak * 0.05).mean())
    level, _ = wav_levels(tmp)
    return voiced, level


def _clean_neighbours(cues: list[Cue], index: dict[int, int], cue: Cue, gap: float = 0.3) -> bool:
    """Cue này có cách xa lượt thoại của người khác không.

    Cắt mẫu ngay sát chỗ người khác vừa nói xong thì dễ dính đuôi giọng của họ,
    và mẫu lai hai giọng làm bản nhân bản nghe không ra ai. Chỉ nhận cue nào mà
    hàng xóm hai bên hoặc cùng người nói, hoặc cách ít nhất `gap` giây.
    """
    i = index.get(id(cue))
    if i is None:
        return True
    for j in (i - 1, i + 1):
        if not (0 <= j < len(cues)):
            continue
        other = cues[j]
        if (other.speaker or "") == (cue.speaker or ""):
            continue
        distance = cue.start - other.end if j < i else other.start - cue.end
        if distance < gap:
            return False
    return True


def extract_reference(
    video: Path,
    cues: list[Cue],
    out_path: Path,
    min_len: float = 4.0,
    speaker: str = "",
) -> Path:
    """Cắt 4–8 giây **có tiếng nói** từ video để nhân bản giọng.

    Chấm điểm ~15 cue đầu rồi chọn cái tốt nhất, thay vì lấy cái đầu tiên đủ dài.
    Lấy bừa cue đầu là hỏng thật: phụ đề tải về thường mở đầu bằng tên phim hoặc
    lời nhạc mở màn, và khi tắt VAD thì Whisper cũng biến nhạc thành cue. Mẫu rơi
    vào chỗ không có thoại thì model sinh chạy loạn — đo trên video thật, cùng một
    câu: mẫu thoại sạch ra 3,4 giây, mẫu đoạn không thoại ra **24,0 giây** (đúng
    trần sinh), và khi đó MỌI câu đều tràn, đè chồng suốt cả tập.

    Truyền `speaker` thì chỉ xét cue của đúng nhân vật đó, và ưu tiên những cue
    không nằm sát lượt thoại của người khác — đây là chỗ quyết định để mỗi nhân
    vật ra một giọng riêng thay vì mấy giọng lai vào nhau.
    """
    tmp = out_path.parent / (out_path.stem + ".try.wav")
    pool = [c for c in cues if c.speaker == speaker] if speaker else list(cues)
    index = {id(c): i for i, c in enumerate(cues)}

    def usable(c: Cue) -> bool:
        return c.end - c.start >= min_len and not _NOT_SPEECH.match((c.text or "").strip())

    # Vòng 1: cue đủ dài, có thoại, và không sát lượt của người khác
    candidates = [c for c in pool if usable(c) and _clean_neighbours(cues, index, c)][:15]
    # Vòng 2: nới điều kiện hàng xóm — thà mẫu hơi dính còn hơn không có mẫu
    if not candidates:
        candidates = [c for c in pool if usable(c)][:15]
    if not candidates and pool:
        candidates = [max(pool, key=lambda c: c.end - c.start)]
    if not candidates and cues:
        candidates = [max(cues, key=lambda c: c.end - c.start)]

    best, best_score = None, (-1.0, -99.0)
    for cue in candidates:
        voiced, level = _score_reference(video, cue, tmp, min_len)
        # đủ tiếng nói là điều kiện chính, mức to là tiêu chí phụ
        score = (voiced, level)
        if score > best_score:
            best, best_score = cue, score
        if voiced >= 0.85:
            break
    tmp.unlink(missing_ok=True)

    if best is None:
        raise DubError("Không có đoạn nào đủ dài để cắt mẫu nhân bản giọng.")

    length = min(8.0, max(min_len, best.end - best.start))
    media.run_ffmpeg_progress(
        [
            "-ss", f"{best.start:.2f}", "-t", f"{length:.2f}",
            "-i", str(Path(video).resolve()),
            "-vn", "-ac", "1", "-ar", "24000", "-c:a", "pcm_s16le",
            str(out_path.resolve()),
        ],
        0.0,
    )
    if not out_path.exists():
        raise DubError("Không cắt được đoạn mẫu để nhân bản giọng.")
    # Guard cũ là `size < 2048`: wav im lặng 5 giây nặng 240 KB nên qua được hết.
    level, _ = wav_levels(out_path)
    if level <= -40.0 or best_score[0] < 0.30:
        raise DubError(
            f"Đoạn mẫu cắt được gần như không có tiếng nói "
            f"(mức {level:.0f} dBFS, {best_score[0]*100:.0f}% khung có tiếng). "
            "Chọn một giọng có sẵn, hoặc sửa mốc giờ phụ đề cho trúng đoạn có thoại."
        )
    return out_path


def speaker_ids(cues: list[Cue]) -> list[str]:
    """Nhãn nhân vật có trong `cues`, sắp theo tổng thời gian nói giảm dần."""
    talk: dict[str, float] = {}
    for c in cues:
        sid = (c.speaker or "").strip()
        if sid:
            talk[sid] = talk.get(sid, 0.0) + max(0.0, c.end - c.start)
    return sorted(talk, key=lambda s: (-talk[s], s))


def extract_references(
    video: Path,
    cues: list[Cue],
    workdir: Path,
    min_len: float = 4.0,
    only: set[str] | None = None,
    on_log: Callable[[str], None] | None = None,
    on_progress: Callable[[float], None] | None = None,
) -> tuple[dict[str, str], list[str]]:
    """Cắt mẫu giọng riêng cho **từng nhân vật** trong video.

    Trả về ``(map nhãn -> đường dẫn wav, danh sách nhãn không cắt được)``.

    Cố ý KHÔNG để một nhân vật hỏng làm sập cả job: cắt trượt nhân vật nào thì
    ghi tên nhân vật đó vào danh sách thứ hai để bên gọi cấp một giọng dựng sẵn
    thay thế. Cảnh phụ chỉ có hai câu thoại lí nhí là ca rất thường gặp, và bỏ
    cả bản lồng tiếng chỉ vì nó thì vô lý.
    """
    ids = [s for s in speaker_ids(cues) if only is None or s in only]
    refs: dict[str, str] = {}
    failed: list[str] = []

    for n, sid in enumerate(ids, 1):
        out_path = workdir / f"voice_ref_{sid}.wav"
        try:
            extract_reference(video, cues, out_path, min_len=min_len, speaker=sid)
            refs[sid] = str(out_path)
            if on_log:
                on_log(f"  {sid}: đã cắt mẫu giọng ({out_path.name}).")
        except Exception as exc:
            failed.append(sid)
            out_path.unlink(missing_ok=True)
            if on_log:
                on_log(f"  {sid}: không cắt được mẫu ({exc}) — sẽ dùng giọng dựng sẵn.")
        if on_progress:
            on_progress(n / max(1, len(ids)))

    return refs, failed


def _spoken_text(cue: Cue, use_translation: bool, add_stop: bool = True) -> str:
    """Chữ sẽ đưa vào TTS cho một cue, hoặc rỗng nếu không có gì đọc được.

    Cố ý KHÔNG rơi về `cue.text` khi thiếu bản dịch. Trước đây có fallback đó,
    nên chỉ cần một dòng dịch lỗi là dòng ấy bị đọc bằng nguyên văn tiếng Trung
    qua giọng tiếng Việt; và nếu cả tập không có bản dịch nào thì đọc nguyên văn
    tiếng Trung từ đầu tới cuối — ra một tập tiếng bịa mà log vẫn báo thành công.
    Thà bỏ trống rồi chỉ rõ dòng nào để người dùng dịch lại.
    """
    if use_translation:
        return _clean_for_tts(cue.text2 or "", add_stop=add_stop)
    return _clean_for_tts(cue.text or "", add_stop=add_stop)


def speech_units(cues: list[Cue], use_translation: bool = True) -> list[dict]:
    """Gộp cue thành **đơn vị đọc**: một câu trọn = một lần đọc TTS.

    Vì sao phải gộp: phụ đề được cắt theo giới hạn ký tự chứ không theo ngữ
    pháp (Whisper tiếng Trung gần như không trả dấu câu — đo thật: 18 dấu trên
    1768 ký tự, 53/69 cue bị cắt vì đủ 28 ký tự). Sau đó `translate` gom cue
    thành câu để dịch trọn ý, rồi **chia lại bản dịch theo tỉ lệ số ký tự**, nên
    68/69 cue nhận một mảnh cụt: 48 mảnh không kết thúc bằng dấu câu, 41 chỗ một
    từ bị chẻ đôi.

    Nếu đọc từng mảnh đó thì TTS xuống giọng và nghỉ ngay giữa từ, và nội dung
    tiếng Việt rơi lệch khỏi chỗ đáng nói (đo được: lệch trung vị 550 ms, tới
    1,3 s). Nối lại rồi đọc trọn câu trong đúng khoảng thời gian của cả nhóm thì
    hết cả hai chuyện.

    `translate._cut_near` cắt đúng vào khoảng trắng nên nối lại bằng
    `_join_fragments` phục hồi nguyên văn bản dịch.
    """
    from .translate import _join_fragments, group_cues

    units: list[dict] = []
    for g in group_cues(cues):
        for same_voice in _split_by_speaker(cues, g):
            for part in _cap_unit(cues, same_voice):
                parts, taken = [], []
                for i in part:
                    # add_stop=False: đây mới là mảnh, dấu chấm chỉ đặt sau khi nối
                    raw = _spoken_text(cues[i], use_translation, add_stop=False)
                    if raw:
                        parts.append(raw)
                        taken.append(i)
                text = _clean_for_tts(_join_fragments(parts))
                if not text or not taken:
                    continue
                # `taken` chứ không phải `part`: cue nào không góp chữ nào (thiếu
                # bản dịch, chỉ có dấu câu) thì không được coi là đã đọc — nếu
                # không thì nó lọt khỏi danh sách cảnh báo, và khoảng thời gian
                # bị tính rộng ra phần chẳng ai đọc.
                units.append(
                    {
                        "cues": taken,
                        "start": cues[taken[0]].start,
                        "end": cues[taken[-1]].end,
                        "text": text,
                        "speaker": (cues[taken[0]].speaker or "").strip(),
                    }
                )
    return units


def _split_by_speaker(cues: list[Cue], idx: list[int]) -> list[list[int]]:
    """Chẻ nhóm cue mỗi khi đổi người nói.

    Một đơn vị đọc phải do **đúng một nhân vật** nói. Bỏ bước này thì hai nhân
    vật đối đáp nhanh sẽ bị `group_cues` gom chung vào một câu, đọc bằng một
    giọng duy nhất — mất sạch ý nghĩa của việc tách nhân vật, mà log vẫn báo
    thành công.

    Cue chưa gán nhãn (nhãn rỗng) được coi là một "nhân vật" riêng, nên nó cũng
    không bị dính vào lượt của người khác.
    """
    out: list[list[int]] = []
    cur: list[int] = []
    last: str | None = None
    for i in idx:
        speaker = (cues[i].speaker or "").strip()
        if cur and speaker != last:
            out.append(cur)
            cur = []
        cur.append(i)
        last = speaker
    if cur:
        out.append(cur)
    return out


def _cap_unit(cues: list[Cue], idx: list[int]) -> list[list[int]]:
    """Chẻ đơn vị đọc quá dài, cắt ở khoảng lặng to nhất bên trong.

    Đơn vị càng dài thì nội dung càng trôi được xa chỗ đáng nói (đo thật: bỏ
    chặn thì lệch lớn nhất lên 1040 ms), và câu quá dài cũng làm TTS đọc kém.
    Cắt ở chỗ nghỉ dài nhất là chỗ ít làm hỏng ngữ pháp nhất.
    """
    if len(idx) < 2:
        return [idx]
    span = cues[idx[-1]].end - cues[idx[0]].start
    chars = sum(len(cues[i].text2 or cues[i].text) for i in idx)
    if span <= MAX_UNIT_SPAN and chars <= MAX_UNIT_CHARS:
        return [idx]

    # ranh giới nào bên trong có khoảng lặng to nhất thì cắt ở đó
    best, best_gap = 1, -1.0
    for k in range(1, len(idx)):
        gap = cues[idx[k]].start - cues[idx[k - 1]].end
        if gap > best_gap:
            best, best_gap = k, gap
    return _cap_unit(cues, idx[:best]) + _cap_unit(cues, idx[best:])


def build_dub_track(
    cues: list[Cue],
    total_duration: float,
    workdir: Path,
    voice: str = "",
    ref_audio: str = "",
    style: str = "tu_nhien",
    use_translation: bool = True,
    max_speed: float = 1.5,
    per_cue: bool = False,
    voice_map: dict[str, str] | None = None,
    ref_map: dict[str, str] | None = None,
    on_progress: Callable[[float], None] | None = None,
    on_log: Callable[[str], None] | None = None,
) -> tuple[Path, dict]:
    """Sinh file wav lồng tiếng khớp mốc giờ của `cues`.

    Mặc định đọc theo **câu trọn** (xem `speech_units`). `per_cue=True` thì đọc
    từng cue một như trước — giữ lại để so sánh, chứ nghe kém hơn rõ rệt.

    Lồng tiếng đa nhân vật: truyền `voice_map` (nhãn nhân vật -> id giọng dựng
    sẵn) và/hoặc `ref_map` (nhãn nhân vật -> file mẫu để nhân bản). Nhân vật nào
    không có trong hai bảng đó thì rơi về `ref_audio`/`voice` dùng chung, nên
    hàm vẫn chạy y như cũ khi không truyền gì.
    """
    import numpy as np

    engine = get_engine()
    tmpdir = workdir / "tts_tmp"
    tmpdir.mkdir(parents=True, exist_ok=True)

    if per_cue:
        units = [
            {"cues": [i], "start": c.start, "end": c.end,
             "text": _spoken_text(c, use_translation),
             "speaker": (c.speaker or "").strip()}
            for i, c in enumerate(cues)
        ]
        units = [u for u in units if u["text"]]
    else:
        units = speech_units(cues, use_translation)

    # Dòng có chữ nhưng không đọc được (thiếu bản dịch, hoặc chỉ có dấu câu /
    # chữ Hán) — nói rõ là dòng nào, đừng lặng lẽ bỏ trống.
    voiced = {i for u in units for i in u["cues"]}
    skipped = [
        i + 1 for i, c in enumerate(cues)
        if i not in voiced and (c.text or c.text2 or "").strip()
    ]
    if skipped and on_log:
        head = ", ".join(str(n) for n in skipped[:12])
        on_log(
            f"⚠ {len(skipped)} dòng không đọc được nên bỏ trống (dòng {head}"
            + ("…" if len(skipped) > 12 else "")
            + "). Thường là chưa có bản dịch, hoặc dòng chỉ có dấu câu / chữ gốc."
        )
    if on_log and not per_cue and units:
        on_log(
            f"Đọc theo câu trọn: {len(cues)} dòng phụ đề gộp thành {len(units)} câu "
            "— tránh đọc cụt giữa từ."
        )

    tail = max((c.end for c in cues), default=0.0)
    total = max(total_duration, tail) + 0.5
    track = np.zeros(int(total * SR) + SR, dtype=np.float32)

    stats: dict = {
        "count": 0, "sped_up": 0, "overflow": 0, "failed": 0, "max_factor": 1.0,
        "trimmed_ms": 0.0, "overflow_s": 0.0, "worst": [], "runaway": 0,
        "skipped": len(skipped),
    }
    first_error = ""
    stats["units"] = len(units)

    for u, unit in enumerate(units):
        text = unit["text"]
        first_cue, last_cue = unit["cues"][0], unit["cues"][-1]
        label = (
            f"dòng {first_cue + 1}"
            if first_cue == last_cue
            else f"dòng {first_cue + 1}–{last_cue + 1}"
        )
        try:
            kwargs = {"style": style}
            # Giọng riêng của nhân vật này; không có thì dùng giọng chung.
            speaker = (unit.get("speaker") or "").strip()
            unit_ref = (ref_map or {}).get(speaker) or ref_audio
            unit_voice = (voice_map or {}).get(speaker) or voice
            if unit_ref:
                kwargs["ref_audio"] = unit_ref
                kwargs["denoise"] = True
            elif unit_voice:
                kwargs["voice"] = unit_voice
            audio = engine.infer(text, **kwargs)
        except Exception as exc:
            stats["failed"] += 1
            if not first_error:
                first_error = str(exc)
            if on_log:
                on_log(f"{label} đọc lỗi, bỏ qua: {exc}")
            # Lỗi ngay từ đầu thường là lỗi cấu hình (thiếu thư viện, sai giọng…)
            # -> dừng sớm thay vì chạy hết rồi xuất ra video không tiếng.
            if stats["failed"] >= 3 and stats["count"] == 0:
                raise DubError(
                    f"Không đọc được câu nào (đã thử {stats['failed']}). Lỗi đầu tiên: {first_error}"
                ) from exc
            if on_progress:
                on_progress((u + 1) / len(units))
            continue

        audio = np.asarray(audio, dtype=np.float32).reshape(-1)
        if audio.size == 0:
            continue

        # Chốt an toàn: TTS đôi khi không gặp điểm kết thúc và sinh tới trần 24
        # giây. Không chặn thì cục tiếng bịa đó đổ vào track, đè lên mấy câu
        # thoại thật phía sau, mà vẫn được đếm là đọc thành công.
        if _runaway(audio.size / SR, text):
            stats["failed"] += 1
            stats["runaway"] += 1
            if on_log:
                on_log(
                    f"{label}: TTS sinh {audio.size / SR:.1f}s cho {len(text)} ký tự "
                    "— bất thường, bỏ câu này để nó không đè lên câu sau."
                )
            if on_progress:
                on_progress((u + 1) / len(units))
            continue

        # VieNeu-TTS chèn ~100ms lặng ở đầu và ~140ms ở cuối mỗi câu. Không cắt
        # thì mọi câu vào trễ 100ms so với hình — lệch đều, nghe rõ — và mất
        # ~240ms ngân sách mỗi câu, làm câu dài càng dễ tràn.
        audio, trimmed = _trim_silence(audio)
        stats["trimmed_ms"] += trimmed * 1000

        window = unit["end"] - unit["start"]
        gap_after = (cues[last_cue + 1].start - unit["end"]) if last_cue + 1 < len(cues) else 2.0
        gap_before = (unit["start"] - cues[first_cue - 1].end) if first_cue > 0 else unit["start"]
        # Lấn sang khoảng lặng phía sau, và chớm sang phía trước một chút: vào
        # sớm 0.15s gần như không ai nhận ra, còn tràn qua câu sau thì đọc chồng.
        # Chừa 0.02s thôi — lưới cue đóng gói sát nhau, khoảng cách điển hình chỉ
        # 0.04s nên đòi 0.08s là không bao giờ lấn được.
        lead_in = max(0.0, min(MAX_LEAD_IN, gap_before - 0.02))
        allowed = window + max(0.0, gap_after - 0.02) + lead_in

        dur = audio.size / SR
        if dur > allowed and allowed > 0.2:
            factor = min(max_speed, dur / allowed)
            audio = _time_stretch(audio, factor, tmpdir, str(u))
            stats["sped_up"] += 1
            stats["max_factor"] = max(stats["max_factor"], factor)
            dur = audio.size / SR
            if dur > allowed + 0.05:
                over = dur - allowed
                stats["overflow"] += 1
                stats["overflow_s"] += over
                # Giữ lại mấy câu tràn nặng nhất để chỉ đúng chỗ cho người dùng
                stats["worst"].append(
                    {
                        "line": label,
                        "over_s": round(over, 2),
                        "chars": len(text),
                        "window_s": round(window, 2),
                        "text": text[:60],
                    }
                )

        # Chỉ vào sớm đúng phần cần, không phải lúc nào cũng lùi
        shift = min(lead_in, max(0.0, dur - (window + max(0.0, gap_after - 0.02))))
        pos = max(0, int((unit["start"] - shift) * SR))
        end = pos + audio.size
        if end > track.size:
            track = np.pad(track, (0, end - track.size))
        # cộng dồn phòng khi hai đoạn chồng nhau
        track[pos:end] += audio
        stats["count"] += 1

        if on_progress:
            on_progress((u + 1) / len(units))

    if units and stats["count"] == 0:
        raise DubError(
            "Không đọc được câu nào." + (f" Lỗi: {first_error}" if first_error else "")
        )

    stats["worst"].sort(key=lambda w: w["over_s"], reverse=True)
    del stats["worst"][8:]

    peak = float(np.max(np.abs(track))) if track.size else 0.0
    if peak > 0.99:
        track = track * (0.99 / peak)

    out = _write_wav(workdir / "dub.wav", track)
    for leftover in tmpdir.glob("*.wav"):
        leftover.unlink(missing_ok=True)
    try:
        tmpdir.rmdir()
    except OSError:
        pass
    return out, stats


# --------------------------------------------------- cân bằng âm lượng

# Mức giọng đọc muốn đạt (RMS phần có tiếng). Giọng TTS ra khoảng -17..-20 dBFS,
# còn thoại trong phim thường -10..-13 dBFS, nên phải kéo lên mới không bị lép.
VOICE_TARGET_DBFS = -16.0
# Giọng đọc cao hơn nền bao nhiêu dB LÚC ĐANG ĐỌC
VOICE_ABOVE_BG_DB = 8.0
# ...và bao nhiêu dB lúc KHÔNG ai đọc. Phải nhỏ, nếu không nền sẽ gào lên mỗi lần
# người đọc ngưng rồi tụt xuống khi đọc lại — nghe giật rất khó chịu.
VOICE_ABOVE_GAP_DB = 3.0
# Kéo/hạ giọng đọc tối đa bao nhiêu dB (đỉnh do limiter ở cuối chuỗi lo, không
# dùng đỉnh để chặn gain — track lồng tiếng luôn bị ghim đỉnh về 0.99 ở
# build_dub_track nên lấy đỉnh làm hạn mức thì gain luôn ra 0)
GAIN_LIMIT_DB = (-6.0, 12.0)
# Trần cuối cùng sau khi trộn; chừa chỗ cho aac vọt lên ~1 dB
OUT_CEILING = 0.89
# Lấy mẫu tiếng gốc bao nhiêu giây để đo (đo cả phim dài mấy tiếng thì quá lâu)
PROBE_SECONDS = 120.0


def _db(x: float) -> float:
    return 20 * math.log10(max(x, 1e-12))


def wav_levels(path: Path) -> tuple[float, float]:
    """(mức phần có tiếng, peak) của một wav — đều dBFS.

    Bỏ khoảng lặng khi tính, vì track lồng tiếng im tới 80-90% thời lượng: lấy
    RMS cả file sẽ ra một con số vô nghĩa, thấp hơn mức nghe thật cả chục dB.
    """
    import numpy as np

    samples, _ = _read_wav(path)
    data = np.abs(np.asarray(samples, dtype=np.float32).reshape(-1))
    if not data.size:
        return -99.0, -99.0
    peak = float(data.max())
    if peak <= 1e-6:
        return -99.0, -99.0
    voiced = data[data > peak * 0.02]
    if not voiced.size:
        return -99.0, _db(peak)
    return _db(float(np.sqrt((voiced.astype(np.float64) ** 2).mean()))), _db(peak)


def original_level(video: Path, duration: float = 0.0, tmpdir: Path | None = None) -> float | None:
    """Mức tiếng gốc (dBFS), lấy mẫu ~2 phút ở giữa video. None nếu không có tiếng.

    File tạm ghi vào `tmpdir` — KHÔNG ghi cạnh video nguồn, vì nguồn có thể nằm
    trên ổ chỉ-đọc hay ổ mạng; ghi lỗi thì cả bước cân âm lượng bị bỏ im lặng.
    """
    video = Path(video)
    start = max(0.0, (duration - PROBE_SECONDS) / 2) if duration > PROBE_SECONDS else 0.0
    probe = Path(tmpdir or video.parent) / f".probe_{video.stem[:20]}.wav"
    try:
        subprocess.run(
            [
                media.ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
                "-ss", f"{start:.2f}", "-t", f"{PROBE_SECONDS:.0f}", "-i", str(video.resolve()),
                "-vn", "-ac", "1", "-ar", "48000", "-c:a", "pcm_s16le", str(probe),
            ],
            check=True, capture_output=True,
            creationflags=(0x08000000 if sys.platform == "win32" else 0),
        )
        level, _ = wav_levels(probe)
    except Exception:
        return None
    finally:
        probe.unlink(missing_ok=True)
    return None if level <= -90 else level


def balance(
    dub_wav: Path,
    video: Path,
    original_volume: float,
    duration: float = 0.0,
    boost: float = 1.0,
    duck: bool = True,
    keep_original: bool = True,
    tmpdir: Path | None = None,
    on_log=None,
) -> tuple[float, float, float]:
    """Tính (dub_volume, mức nền, độ né) từ số đo thật.

    Trả về:
        dub_volume  -- hệ số nhân cho giọng đọc
        bg_volume   -- mức tiếng gốc: lúc KHÔNG ai đọc nếu bật ducking, còn tắt
                       ducking thì là mức đều suốt cả video
        duck_db     -- ducking hụp thêm bao nhiêu dB lúc có người đọc (0 nếu tắt)

    Hai điều dễ làm sai, đã tránh:

    * KHÔNG lấy đỉnh làm hạn mức cho gain. `build_dub_track` ghim đỉnh track về
      0.99, nên đỉnh gần như luôn ~-0.1 dBFS; lấy nó làm trần thì gain luôn ra 0
      và giọng vĩnh viễn ở mức thô. Đỉnh do limiter ở cuối chuỗi mux lo.
    * Mức nền tính theo ĐÚNG nhánh filter sẽ chạy. Bật ducking thì nền có hai
      mức (lúc nghỉ / lúc đọc) và phải đặt mức lúc nghỉ **thấp hơn giọng** —
      nếu để nền chạy 100% ở đoạn nghỉ thì phim gào lên rồi tụt xuống mỗi lần
      người đọc ngưng, đó mới là cái nghe khó chịu nhất.
    """
    voice, peak = wav_levels(dub_wav)
    if voice <= -90:
        if on_log:
            on_log("Track lồng tiếng gần như không có tiếng — bỏ qua bước cân âm lượng.")
        return boost, original_volume, 0.0

    # 1. chuẩn hoá giọng đọc về mức mong muốn
    want = VOICE_TARGET_DBFS - voice
    lo, hi = GAIN_LIMIT_DB
    gain_db = max(lo, min(want, hi))
    voice_after = voice + gain_db

    if on_log:
        how = f"{gain_db:+.1f} dB" if abs(gain_db) > 0.05 else "không đổi"
        on_log(
            f"Cân âm lượng — giọng đọc thô {voice:.1f} dBFS (đỉnh {peak:.1f}) → {how} "
            f"→ {voice_after:.1f} dBFS."
        )

    if not keep_original or original_volume <= 0.001:
        if on_log:
            on_log("  Không giữ tiếng gốc — chỉ còn giọng đọc.")
        return 10 ** (gain_db / 20) * boost, 0.0, 0.0

    src = original_level(video, duration, tmpdir=tmpdir)
    if src is None:
        if on_log:
            on_log("  Không đo được tiếng gốc (video im, hoặc không đọc được) — giữ nền như bạn đặt.")
        return 10 ** (gain_db / 20) * boost, original_volume, 0.0

    if duck:
        # Nền lúc nghỉ đặt thấp hơn giọng VOICE_ABOVE_GAP_DB, còn lúc đọc thì
        # hụp thêm cho đủ VOICE_ABOVE_BG_DB. Chênh nhau ít nên không bị bơm.
        #
        # `original_volume` là TRẦN do người dùng đặt: tool chỉ được hạ xuống,
        # không được tự nâng lên — nâng lên thì thanh trượt thành vô nghĩa.
        gap_db = (voice_after - VOICE_ABOVE_GAP_DB) - src
        want_bg = 10 ** (max(-30.0, min(0.0, gap_db)) / 20)
        bg_volume = max(0.02, min(original_volume, want_bg))
        duck_db = VOICE_ABOVE_BG_DB - VOICE_ABOVE_GAP_DB
        if on_log:
            rest = src + _db(bg_volume)
            on_log(
                f"  Tiếng gốc {src:.1f} dBFS → nền {bg_volume * 100:.0f}% = {rest:.1f} dBFS "
                f"lúc không ai đọc (thấp hơn giọng {voice_after - rest:.1f} dB), "
                f"hụp thêm {duck_db:.0f} dB lúc đang đọc."
            )
    else:
        bg_volume = original_volume
        short = max(0.0, (src + _db(bg_volume) + VOICE_ABOVE_BG_DB) - voice_after)
        if short > 0.05:
            bg_volume = max(0.0, bg_volume * 10 ** (-short / 20))
        duck_db = 0.0
        if on_log:
            rest = src + _db(bg_volume)
            on_log(
                f"  Tiếng gốc {src:.1f} dBFS → nền giảm đều còn {bg_volume * 100:.0f}% "
                f"= {rest:.1f} dBFS"
                + (f" (hạ thêm {short:.1f} dB)" if short > 0.05 else "")
                + f", giọng hơn nền {voice_after - rest:.1f} dB."
            )

    if boost > 1.001 and on_log:
        on_log(f"  Bạn kéo giọng đọc lên {boost * 100:.0f}% — limiter ở cuối sẽ chặn vỡ tiếng.")
    return 10 ** (gain_db / 20) * boost, bg_volume, duck_db


_filters_cache: set[str] | None = None


def _has_filter(name: str) -> bool:
    global _filters_cache
    if _filters_cache is None:
        try:
            out = subprocess.run(
                [media.ffmpeg_exe(), "-hide_banner", "-filters"],
                capture_output=True, text=True, errors="ignore",
                creationflags=(0x08000000 if sys.platform == "win32" else 0),
            ).stdout
        except Exception:
            out = ""
        _filters_cache = {
            line.split()[1] for line in out.splitlines()
            if len(line.split()) > 2 and line.startswith(" ")
        }
    return name in _filters_cache


def has_ducking() -> bool:
    """ffmpeg hiện tại có `sidechaincompress` để né tiếng gốc theo giọng đọc không."""
    return _has_filter("sidechaincompress")


AFMT = "aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo"


def _limiter() -> str:
    """Chặn vỡ tiếng ở cuối chuỗi. amix dùng normalize=0 nên cộng thẳng, tổng
    giọng + nền có thể vượt full scale rồi bị bộ mã hoá aac chặt cứng -> nghe rè."""
    if _has_filter("alimiter"):
        return f"alimiter=limit={OUT_CEILING:.3f}"
    if _has_filter("acompressor"):
        return f"acompressor=threshold={OUT_CEILING:.3f}:ratio=20:attack=1:release=60:makeup=1"
    return f"volume={OUT_CEILING:.3f}"


def _duck_filter(bg_volume: float, duck_db: float, voice_dbfs: float, dub_volume: float) -> str:
    """Né tiếng gốc theo giọng đọc, dùng chính giọng làm tín hiệu điều khiển.

    `bg_volume` là mức nền lúc KHÔNG ai đọc — phải có, nếu thiếu thì tiếng gốc
    chạy 100% ở mọi khoảng nghỉ và gào lên mỗi lần người đọc ngưng.
    `duck_db` là hụp thêm bao nhiêu dB lúc đang đọc.
    """
    thr_db = -30.0
    thr = 10 ** (thr_db / 20)
    # aformat mono -> stereo chia đều 2 kênh, mỗi kênh thấp hơn 3 dB
    key_db = voice_dbfs + _db(dub_volume) - 3.0
    excess = max(6.0, key_db - thr_db)          # key cao hơn ngưỡng bao nhiêu dB
    depth = max(0.0, min(duck_db, excess - 3.0))
    ratio = 1.0 if depth <= 0.01 else max(1.5, min(8.0, 1 / (1 - depth / excess)))
    return (
        f"[1:a]volume={dub_volume:.3f},{AFMT},asplit=2[vomix][vokey];"
        f"[0:a]volume={bg_volume:.4f},{AFMT}[bg];"
        f"[bg][vokey]sidechaincompress="
        f"threshold={thr:.5f}:ratio={ratio:.2f}:attack=20:release=700:makeup=1:level_sc=1[bgduck];"
        f"[bgduck][vomix]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[mix];"
        f"[mix]{_limiter()}[aout]"
    )


def mux_dub(
    video: Path,
    dub_wav: Path,
    out_path: Path,
    original_volume: float = 0.12,
    dub_volume: float = 1.0,
    keep_original: bool = True,
    duck: bool = True,
    duck_db: float = 0.0,
    voice_dbfs: float = -18.0,
    duration: float = 0.0,
    on_log=None,
    on_progress=None,
) -> Path:
    """Ghép track lồng tiếng vào video.

    keep_original=False  -> thay hẳn tiếng gốc
    keep_original=True   -> giữ tiếng gốc ở `original_volume`, và:
        duck=True  hụp thêm `duck_db` dB lúc người đọc đang nói, đoạn không ai
                   đọc vẫn nghe nguyên nhạc/tiếng động ở mức `original_volume`
        duck=False giảm đều suốt cả video

    Chuỗi nào cũng kết bằng limiter — amix cộng thẳng (normalize=0) nên tổng
    giọng + nền có thể vượt full scale.
    """
    video = Path(video).resolve()
    dub_wav = Path(dub_wav).resolve()
    out_path = Path(out_path)

    # Video không có track tiếng thì không có [0:a] mà trộn — ffmpeg sẽ báo lỗi.
    # Ca này có thật: chế độ "đã có .srt/.vtt" cho phép video im lặng.
    if keep_original:
        try:
            keep_original = bool(media.probe(video).get("has_audio"))
        except Exception:
            pass

    if keep_original and original_volume > 0.001:
        if duck and duck_db > 0.01 and has_ducking():
            filt = _duck_filter(original_volume, duck_db, voice_dbfs, dub_volume)
            mode = f"né theo giọng đọc (hụp {duck_db:.0f} dB)"
        else:
            # aformat cả hai phía: dub.wav là mono 48k, phim có thể 5.1 / 44.1k
            filt = (
                f"[0:a]volume={original_volume:.4f},{AFMT}[bg];"
                f"[1:a]volume={dub_volume:.3f},{AFMT}[vo];"
                f"[bg][vo]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[mix];"
                f"[mix]{_limiter()}[aout]"
            )
            mode = "giảm đều cả video"
        args = [
            "-i", str(video), "-i", str(dub_wav),
            "-filter_complex", filt,
            "-map", "0:v", "-map", "[aout]",
        ]
    else:
        mode = "thay hẳn tiếng gốc"
        args = [
            "-i", str(video), "-i", str(dub_wav),
            "-filter_complex",
            f"[1:a]volume={dub_volume:.3f},{AFMT}[mix];[mix]{_limiter()}[aout]",
            "-map", "0:v", "-map", "[aout]",
        ]

    args += [
        "-c:v", "copy",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
        "-shortest", "-movflags", "+faststart",
        str(out_path.resolve()),
    ]
    if on_log:
        on_log(f"Trộn tiếng: {mode}, chặn vỡ tiếng bằng `{_limiter().split('=')[0]}`.")
    media.run_ffmpeg_progress(args, duration, on_progress)
    return out_path


def preview(text: str, voice: str = "", style: str = "tu_nhien", out_path: Path | None = None) -> Path:
    """Đọc thử một câu để nghe giọng."""
    engine = get_engine()
    kwargs = {"style": style}
    if voice:
        kwargs["voice"] = voice
    audio = engine.infer(_clean_for_tts(text) or "Xin chào, đây là giọng đọc thử.", **kwargs)
    out_path = out_path or Path("preview.wav")
    return _write_wav(out_path, audio)
