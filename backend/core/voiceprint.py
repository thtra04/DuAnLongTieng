"""Tách NHIỀU người nói cùng giới bằng véc-tơ giọng, và đoán nhóm tuổi.

`gender.py` chỉ chia được hai nhóm nam / nữ. Phim có hai ba người đàn ông thì cả ba
bị gộp một vai. Module này chia nhỏ tiếp trong từng nhóm giới bằng véc-tơ đặc trưng
người nói (pyannote WeSpeaker, đã có trong cache khi cài `diarize`; **không cần token**
vì model này công khai), không cần chạy pipeline phân đoạn người nói cả phim.

Luồng::

    audio.wav -> véc-tơ giọng của từng cue đủ dài -> theo giới tính (F0) chia nhóm
              -> gom cụm phân cấp (cosine, liên kết trung bình) trong từng nhóm
              -> cue ngắn gán theo tâm cụm gần nhất -> nhãn S1, S2… theo thời gian nói

Nhóm tuổi (`age_of`) chỉ tự đoán được TRẺ EM, từ cao độ: giọng trẻ em cao hơn hẳn giọng
người lớn cùng giới. Người cao tuổi không có dấu hiệu cao độ nào đáng tin (âm sắc khàn,
run mới là dấu hiệu, mà cần model huấn luyện riêng) nên để người dùng chọn tay.
"""

from __future__ import annotations

import wave
from pathlib import Path
from typing import Callable

import numpy as np

from .subtitles import Cue

CHILD, ADULT, ELDER = "C", "A", "E"
AGE_NAMES = {CHILD: "Trẻ em", ADULT: "Người lớn", ELDER: "Cao tuổi"}

MODEL_ID = "pyannote/wespeaker-voxceleb-resnet34-LM"
SR = 16000
# Cue ngắn hơn ngần này không đủ để lấy véc-tơ giọng đáng tin
MIN_EMBED_S = 1.2
# Hai cụm cùng giới có độ giống trung bình (cosine) từ ngưỡng này trở lên thì là MỘT người.
# Chọn trên thoại thật (clip bilibili, có nhạc nền và cảm xúc): cùng một người chỉ giống nhau
# ~0,4–0,5 nên ngưỡng 0,45 trở lên tách thừa tới 8–9 vai; 0,35 cho 1 nam + 2 nữ. Đổi lại,
# hai giọng TTS gần như nhau (Minh Đức / Thanh Bình) bị gộp. Xem data/_bench/voiceprint_*.py
MERGE_SIM = 0.35
# Cụm ít hơn ngần này giây tiếng nói thì dồn vào cụm gần nhất, tránh đẻ ra vai "ma"
MIN_CLUSTER_S = 4.0
MAX_PER_GENDER = 6
# Ngưỡng gộp thích nghi: ratio × độ giống láng giềng gần nhất, kẹp trong [MIN_MERGE, MAX_MERGE]
SIM_RATIO = 0.7
MIN_MERGE, MAX_MERGE = 0.3, 0.7

# Cao độ trung vị từ ngưỡng này trở lên thì coi là giọng trẻ em (người lớn: nam ~85–155,
# nữ ~165–255 Hz; trẻ em ~250–400 Hz). Nam trẻ em có thể chỉ ~230 Hz nên ngưỡng nam thấp hơn.
CHILD_HZ = {"M": 215.0, "F": 285.0}

_model = None


# ------------------------------------------------------------------ nhóm tuổi


def age_of(gender_code: str, f0: float) -> str:
    """`"C"` nếu cao độ vượt ngưỡng trẻ em của giới đó, `"A"` nếu không, `""` nếu chưa biết."""
    if not f0 or f0 <= 0 or gender_code not in CHILD_HZ:
        return ""
    return CHILD if f0 >= CHILD_HZ[gender_code] else ADULT


# ----------------------------------------------------------------- véc-tơ giọng


def available() -> tuple[bool, str]:
    try:
        import torch  # noqa: F401
        from pyannote.audio import Inference, Model  # noqa: F401
    except Exception as exc:
        return False, f"Chưa cài pyannote/torch ({exc.__class__.__name__}). Cài extra `diarize`."
    return True, ""


def _load():
    global _model
    if _model is None:
        from pyannote.audio import Inference, Model

        _model = Inference(Model.from_pretrained(MODEL_ID), window="whole")
    return _model


def _read(wav_path: str | Path, cue: Cue) -> np.ndarray:
    with wave.open(str(wav_path), "rb") as w:
        sr, ch, total = w.getframerate(), w.getnchannels(), w.getnframes()
        a = max(0, min(total, int(cue.start * sr)))
        b = max(a, min(total, int(cue.end * sr)))
        w.setpos(a)
        x = np.frombuffer(w.readframes(b - a), dtype="<i2").astype(np.float32) / 32768.0
    if ch > 1:
        x = x.reshape(-1, ch).mean(axis=1)
    if sr != SR and x.size:
        idx = np.linspace(0, x.size - 1, int(x.size * SR / sr))
        x = np.interp(idx, np.arange(x.size), x).astype(np.float32)
    return x


def embed_array(samples, sr: int):
    """Véc-tơ giọng đã chuẩn hoá của một mảng âm thanh mono; `None` nếu quá ngắn."""
    import torch

    x = np.asarray(samples, dtype=np.float32).reshape(-1)
    if x.size < sr * MIN_EMBED_S:
        return None
    if sr != SR:
        idx = np.linspace(0, x.size - 1, int(x.size * SR / sr))
        x = np.interp(idx, np.arange(x.size), x).astype(np.float32)
    v = np.asarray(_load()({"waveform": torch.from_numpy(np.ascontiguousarray(x))[None], "sample_rate": SR})).reshape(-1)
    return v / (np.linalg.norm(v) + 1e-9)


def embed_cues(wav_path, cues: list[Cue], on_progress: Callable[[float], None] | None = None):
    """Véc-tơ giọng đã chuẩn hoá của từng cue; `None` cho cue quá ngắn."""
    import torch

    model = _load()
    out: list[np.ndarray | None] = []
    for i, cue in enumerate(cues):
        if cue.end - cue.start < MIN_EMBED_S:
            out.append(None)
        else:
            x = _read(wav_path, cue)
            v = np.asarray(model({"waveform": torch.from_numpy(x)[None], "sample_rate": SR})).reshape(-1)
            out.append(v / (np.linalg.norm(v) + 1e-9))
        if on_progress:
            on_progress((i + 1) / max(1, len(cues)))
    return out


# --------------------------------------------------------------------- gom cụm


def cluster(vecs: np.ndarray, weights: np.ndarray, merge_sim: float = MERGE_SIM) -> list[int]:
    """Gom cụm phân cấp, liên kết trung bình theo cosine. Trả về chỉ số cụm của từng véc-tơ.

    Dừng khi hai cụm giống nhất chỉ còn giống nhau dưới `merge_sim`. Quy mô vài trăm cue
    nên viết thẳng bằng numpy, khỏi kéo thêm scikit-learn vào phụ thuộc.
    """
    n = len(vecs)
    if n == 0:
        return []
    groups: list[list[int]] = [[i] for i in range(n)]
    sim = vecs @ vecs.T

    def avg(a: list[int], b: list[int]) -> float:
        wa, wb = weights[a][:, None], weights[b][None, :]
        return float((sim[np.ix_(a, b)] * wa * wb).sum() / (wa.sum() * wb.sum()))

    while len(groups) > 1:
        best, pair = -2.0, (0, 1)
        for i in range(len(groups)):
            for j in range(i + 1, len(groups)):
                s = avg(groups[i], groups[j])
                if s > best:
                    best, pair = s, (i, j)
        if best < merge_sim:
            break
        i, j = pair
        groups[i] += groups.pop(j)
    label = [0] * n
    for k, g in enumerate(groups):
        for i in g:
            label[i] = k
    return label


def adaptive_merge_sim(vecs: np.ndarray, ratio: float = SIM_RATIO) -> float:
    """Ngưỡng gộp theo độ "sạch" của chính đoạn thoại này.

    Thoại sạch (TTS, phòng thu): cùng một người giống nhau ~0,85 nên người khác giọng dễ tách.
    Thoại thật có nhạc nền, cảm xúc: cùng một người chỉ giống nhau ~0,45. Ngưỡng cố định không
    chạy được cho cả hai, nên lấy độ giống với 2 láng giềng gần nhất (trung vị) làm mốc nhiễu
    rồi nhân với `ratio`.
    """
    n = len(vecs)
    if n < 3:
        return MERGE_SIM
    sim = vecs @ vecs.T
    np.fill_diagonal(sim, -1.0)
    near = np.sort(sim, axis=1)[:, -2:].mean(axis=1)
    return float(np.clip(ratio * np.median(near), MIN_MERGE, MAX_MERGE))


def split_speakers(
    cues: list[Cue], embeds: list, pitches: list[dict], merge_sim: float | None = None
) -> dict:
    """Gán nhãn S1, S2… cho cue, tách nhiều người trong cùng một giới. Sửa `cues` tại chỗ.

    Trả về ``{"labeled", "empty", "speakers": {nhãn: {"gender", "f0", "age"}}}``.
    Cue không đủ cao độ để biết giới mà có véc-tơ giọng thì theo cụm gần nhất của mọi giới.
    """
    from . import gender as G

    n = len(cues)
    guess = [G.gender_of(p["f0"]) for p in pitches]
    dur = np.array([max(0.0, c.end - c.start) for c in cues])

    stats_thr: dict[str, float] = {}
    clusters: list[dict] = []  # {"gender", "members": [chỉ số cue], "centroid"}
    for g in (G.MALE, G.FEMALE):
        idx = [i for i in range(n) if guess[i] == g and embeds[i] is not None]
        if not idx:
            continue
        vecs = np.stack([embeds[i] for i in idx])
        thr = merge_sim if merge_sim is not None else adaptive_merge_sim(vecs)
        stats_thr[g] = round(thr, 3)
        lab = cluster(vecs, dur[idx], thr)
        for k in sorted(set(lab)):
            mem = [idx[j] for j in range(len(idx)) if lab[j] == k]
            clusters.append({"gender": g, "members": mem})

    def centroid(c):
        v = np.average(np.stack([embeds[i] for i in c["members"]]), axis=0, weights=dur[c["members"]])
        return v / (np.linalg.norm(v) + 1e-9)

    # Cụm quá ít tiếng nói -> dồn vào cụm cùng giới gần nhất (nếu còn cụm khác)
    changed = True
    while changed and len(clusters) > 1:
        changed = False
        for c in sorted(clusters, key=lambda c: dur[c["members"]].sum()):
            if dur[c["members"]].sum() >= MIN_CLUSTER_S:
                continue
            others = [o for o in clusters if o is not c and o["gender"] == c["gender"]]
            if not others:
                continue
            cv = centroid(c)
            tgt = max(others, key=lambda o: float(cv @ centroid(o)))
            tgt["members"] += c["members"]
            clusters.remove(c)
            changed = True
            break
    # Giữ tối đa MAX_PER_GENDER cụm lớn nhất mỗi giới (phần dư dồn vào cụm gần nhất)
    for g in (G.MALE, G.FEMALE):
        same = sorted((c for c in clusters if c["gender"] == g), key=lambda c: -dur[c["members"]].sum())
        for c in same[MAX_PER_GENDER:]:
            cv = centroid(c)
            tgt = max(same[:MAX_PER_GENDER], key=lambda o: float(cv @ centroid(o)))
            tgt["members"] += c["members"]
            clusters.remove(c)

    clusters.sort(key=lambda c: (-dur[c["members"]].sum(), c["gender"]))
    cents = [centroid(c) for c in clusters]
    owner: dict[int, int] = {}
    for k, c in enumerate(clusters):
        for i in c["members"]:
            owner[i] = k

    # Cue chưa vào cụm nào: có véc-tơ -> cụm gần nhất (trong giới đã đoán nếu có);
    # chỉ có cao độ -> cụm lớn nhất của giới đó; còn lại để trống.
    for i in range(n):
        if i in owner or not clusters:
            continue
        cand = [k for k, c in enumerate(clusters) if not guess[i] or c["gender"] == guess[i]] or list(range(len(clusters)))
        if embeds[i] is not None:
            owner[i] = max(cand, key=lambda k: float(embeds[i] @ cents[k]))
        elif guess[i]:
            owner[i] = cand[0]

    stats = {"labeled": 0, "empty": 0, "speakers": {}, "threshold": stats_thr}
    for i, cue in enumerate(cues):
        if i in owner:
            cue.speaker = f"S{owner[i] + 1}"
            stats["labeled"] += 1
        else:
            cue.speaker = ""
            stats["empty"] += 1
    for k, c in enumerate(clusters):
        mem = [i for i in range(n) if owner.get(i) == k]
        vals = [(pitches[i]["f0"], pitches[i]["voiced"]) for i in mem if pitches[i]["f0"] > 0]
        f0 = G._weighted_median([v for v, _ in vals], [w for _, w in vals]) if vals else 0.0
        stats["speakers"][f"S{k + 1}"] = {
            "gender": c["gender"], "f0": round(f0, 1), "age": age_of(c["gender"], f0),
        }
    return stats
