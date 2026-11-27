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

from . import gender as G
from .diarize import speakers_of
from .subtitles import Cue

CHILD, ADULT, ELDER = "C", "A", "E"
AGE_NAMES = {CHILD: "Trẻ em", ADULT: "Người lớn", ELDER: "Cao tuổi"}

MODEL_ID = "pyannote/wespeaker-voxceleb-resnet34-LM"
SR = 16000
# Cue ngắn hơn ngần này không đủ để lấy véc-tơ giọng đáng tin cho việc GOM CỤM
MIN_EMBED_S = 1.2
# ...nhưng vẫn đủ để GÁN vào cụm đã có. Đo trên trích đoạn 86 giây có nhãn tay: 14/43 câu ngắn hơn
# 1,2 giây ("老爷", "这是谁"), trước đây chỉ được gán theo cao độ nên rơi vào vai nữ lớn nhất; lấy véc-tơ từ
# 0,4 giây thì mọi câu đều gần tâm đúng nhân vật của nó (data/_bench/speaker_explore.py).
MIN_ASSIGN_S = 0.4
# Hai cụm cùng giới có độ giống trung bình (cosine) từ ngưỡng này trở lên thì là MỘT người.
# Chọn trên thoại thật (clip bilibili, có nhạc nền và cảm xúc): cùng một người chỉ giống nhau
# ~0,4–0,5 nên ngưỡng 0,45 trở lên tách thừa tới 8–9 vai; 0,35 cho 1 nam + 2 nữ. Đổi lại,
# hai giọng TTS gần như nhau (Minh Đức / Thanh Bình) bị gộp. Xem data/_bench/voiceprint_*.py
MERGE_SIM = 0.35
# Cụm ít hơn ngần này giây tiếng nói thì dồn vào cụm gần nhất, tránh đẻ ra vai "ma"
MIN_CLUSTER_S = 4.0
# ...hoặc ít hơn tỉ lệ này của tổng thời lượng thoại (video dài): video 16 phút từ 16 cụm / 4 vai ma
# còn 9 vai, video 13 phút từ 22 / 6 còn 10 / 1 (data/_bench/speaker_minfrac.py)
MIN_CLUSTER_FRAC = 0.015
MAX_PER_GENDER = 6
# Chia nam / nữ theo cao độ TỪNG CÂU trước khi gom cụm làm vỡ một người thành hai vai: nam quát to
# lên 205–220 Hz bị đẩy sang nhóm nữ, thành vai "Nữ 2". Cụm nào giống một cụm KHÁC GIỚI lớn hơn từ
# ngưỡng này trở lên, và giống nó hơn hẳn mọi cụm cùng giới, thì gộp vào.
XMERGE_SIM = 0.45
XMERGE_GAP = 0.1
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
    """Véc-tơ giọng đã chuẩn hoá của từng cue; `None` cho cue quá ngắn (dưới `MIN_ASSIGN_S`)."""
    import torch

    model = _load()
    out: list[np.ndarray | None] = []
    for i, cue in enumerate(cues):
        if cue.end - cue.start < MIN_ASSIGN_S:
            out.append(None)
        else:
            x = _read(wav_path, cue)
            # A padded subtitle can extend beyond the audio or contain only silence.
            if x.size < SR * MIN_ASSIGN_S or not np.any(np.abs(x) > 0.005):
                out.append(None)
            else:
                v = np.asarray(model({"waveform": torch.from_numpy(x)[None], "sample_rate": SR})).reshape(-1)
                norm = np.linalg.norm(v)
                out.append(v / norm if np.isfinite(norm) and norm > 0 else None)
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

    1. Gom cụm trong từng giới (đoán theo cao độ), ưu tiên câu đủ dài (`MIN_EMBED_S`).
    2. Cụm quá ít tiếng nói (dưới `MIN_CLUSTER_S` hoặc `MIN_CLUSTER_FRAC` tổng thoại) dồn vào
       cụm cùng giới gần nhất.
    3. Cụm bị chia nhầm giới (nam nói to, nữ nói trầm) gộp vào cụm khác giới nó giống hẳn.
    4. Tìm vai phụ từ các câu ngắn lặp lại, khác các giọng đã biết. Mỗi giới giữ tối đa `MAX_PER_GENDER` cụm.
    5. MỌI câu có véc-tơ — kể cả câu ngắn và câu đã nằm trong cụm — về tâm gần nhất, không chặn
       theo giới: cao độ một câu lẻ kém tin hơn véc-tơ giọng.
    """
    n = len(cues)
    guess = [G.gender_of(p["f0"]) for p in pitches]
    dur = np.array([max(0.0, c.end - c.start) for c in cues])
    min_share = MIN_CLUSTER_FRAC * float(dur.sum())
    min_cluster = max(MIN_CLUSTER_S, min_share)

    stats_thr: dict[str, float] = {}
    clusters: list[dict] = []  # {"gender", "members": [chỉ số cue], "centroid"}
    for g in (G.MALE, G.FEMALE):
        eligible = [i for i in range(n) if guess[i] == g and embeds[i] is not None]
        # A character may have *only* short replies. Don't force those replies
        # into another character's cluster just because it has longer examples.
        idx = [i for i in eligible if dur[i] >= MIN_EMBED_S] or eligible
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
            if dur[c["members"]].sum() >= min_cluster:
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
    # Cụm bị chia nhầm giới -> gộp vào cụm khác giới lớn hơn mà nó giống hẳn
    changed = True
    while changed and len(clusters) > 1:
        changed = False
        for c in sorted(clusters, key=lambda c: dur[c["members"]].sum()):
            cv = centroid(c)
            same = [float(cv @ centroid(o)) for o in clusters if o is not c and o["gender"] == c["gender"]]
            opp = [o for o in clusters if o["gender"] != c["gender"]
                   and dur[o["members"]].sum() > dur[c["members"]].sum()]
            if not opp:
                continue
            tgt = max(opp, key=lambda o: float(cv @ centroid(o)))
            s_opp = float(cv @ centroid(tgt))
            if s_opp >= XMERGE_SIM and s_opp >= max(same, default=-1.0) + XMERGE_GAP:
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
    # A supporting voice may never get a long, clean subtitle of its own.
    # Require repeated, mutually similar short replies that fit *none* of the known voices.
    for g, threshold in stats_thr.items():
        slots = MAX_PER_GENDER - sum(c["gender"] == g for c in clusters)
        short = [i for i in range(n) if guess[i] == g and embeds[i] is not None
                 and MIN_ASSIGN_S <= dur[i] < MIN_EMBED_S
                 and max(float(embeds[i] @ v) for v in cents) < threshold]
        if slots <= 0 or len(short) < 2:
            continue
        # Short samples are noisier than the long anchors. Form candidates at
        # the similarity floor; their pooled voice must still fail the normal match.
        labels = cluster(np.stack([embeds[i] for i in short]), dur[short],
                         MIN_MERGE if merge_sim is None else merge_sim)
        groups: dict[int, list[int]] = {}
        for i, k in zip(short, labels):
            groups.setdefault(k, []).append(i)
        for members in sorted(groups.values(), key=lambda m: -dur[m].sum()):
            if len(members) < 2 or dur[members].sum() < max(MIN_EMBED_S, min_share):
                continue
            candidate = {"gender": g, "members": members}
            center = centroid(candidate)
            if max(float(center @ v) for v in cents) < threshold:
                clusters.append(candidate)
                cents.append(center)
                slots -= 1
                if not slots:
                    break
    owner: dict[int, int] = {}
    # Mọi câu có véc-tơ -> tâm gần nhất (mọi giới). Câu chỉ có cao độ -> cụm lớn nhất cùng giới;
    # không có gì -> để trống.
    for i in range(n):
        if not clusters:
            break
        if embeds[i] is not None:
            owner[i] = int(np.argmax([float(embeds[i] @ v) for v in cents]))
        elif guess[i]:
            cand = [k for k, c in enumerate(clusters) if c["gender"] == guess[i]]
            if cand:
                owner[i] = cand[0]
    # cụm có thể rỗng sau bước trên -> đánh số lại theo thời lượng nói thật
    used = sorted({k for k in owner.values()}, key=lambda k: -sum(dur[i] for i in owner if owner[i] == k))
    remap = {k: r for r, k in enumerate(used)}
    owner = {i: remap[k] for i, k in owner.items()}
    clusters = [clusters[k] for k in used]

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


def _keep_cast(cues: list[Cue], previous: list[str], embeds: list | None, reserved_ids) -> None:
    """Keep cast IDs stable; use explicitly assigned lines as voice examples."""
    groups: dict[str, list[int]] = {}
    votes: dict[tuple[str, str], float] = {}
    for i, (cue, old) in enumerate(zip(cues, previous)):
        if cue.speaker:
            groups.setdefault(cue.speaker, []).append(i)
            if old:
                pair = (cue.speaker, old)
                votes[pair] = votes.get(pair, 0.0) + cue.end - cue.start

    mapping: dict[str, str] = {}
    for auto, old in sorted(votes, key=lambda p: (-votes[p], p)):
        if auto not in mapping and old not in mapping.values():
            mapping[auto] = old
    reserved = set(previous).union(reserved_ids)
    number = 1
    for auto in sorted(groups, key=lambda label: int(label[1:])):
        indices = groups[auto]
        if auto not in mapping:
            while f"S{number}" in reserved:
                number += 1
            mapping[auto] = f"S{number}"
            reserved.add(mapping[auto])
        default = mapping[auto]
        for i in indices:
            cues[i].speaker = default

        # Two similar voices may share one automatic cluster. Only split that
        # cluster when the editor supplies counterexamples, not by guessing a cast size.
        if embeds is None:
            if len({previous[i] for i in indices if previous[i]}) > 1:
                for i in indices:
                    cues[i].speaker = previous[i]  # Pitch cannot distinguish these cast members.
            continue
        examples: dict[str, list[int]] = {}
        for i in indices:
            if cues[i].speaker_fixed and previous[i] and embeds[i] is not None:
                examples.setdefault(previous[i], []).append(i)
        if not (examples.keys() - {default}):
            continue
        if default not in examples:
            rest = [i for i in indices if not cues[i].speaker_fixed and embeds[i] is not None]
            if not rest:
                continue
            examples[default] = rest
        centers = {}
        for label, members in examples.items():
            center = np.average([embeds[i] for i in members], axis=0,
                                weights=[cues[i].end - cues[i].start for i in members])
            centers[label] = center / (np.linalg.norm(center) + 1e-9)
        for i in indices:
            if not cues[i].speaker_fixed and embeds[i] is not None:
                scores = {k: float(embeds[i] @ v) for k, v in centers.items()}
                best = max(scores, key=scores.get)
                if scores[best] >= MIN_MERGE and scores[best] > scores[default]:
                    cues[i].speaker = best
    for cue, old in zip(cues, previous):
        if cue.speaker_fixed or not cue.speaker or (embeds is None and old):
            cue.speaker = old


def identify(wav: Path, cues: list[Cue], *, use_embeddings: bool = True, on_log=None,
             on_progress=None, reserved_ids=()) -> tuple[list[dict], str]:
    """Identify voices without changing dialogue, timings, or any project on disk."""
    previous = [c.speaker for c in cues]
    pitches = G.measure(wav, cues)
    if not any(p["f0"] for p in pitches):
        return [], "pitch"
    embeds = None
    method = "pitch"
    info = {}
    if use_embeddings:
        try:
            if on_log:
                on_log("Lấy véc-tơ giọng từng câu để tách nhiều người cùng giới…")
            embeds = embed_cues(wav, cues, on_progress=on_progress)
            stats = split_speakers(cues, embeds, pitches)
            if stats["labeled"]:
                info = stats["speakers"]
                method = "voiceprint"
        except Exception as exc:
            embeds = None
            if on_log:
                on_log(f"Không dùng được véc-tơ giọng ({exc}), chuyển sang phân theo cao độ.")
    if method == "pitch":
        embeds = None
        G.split_cues(cues, pitches)
    if reserved_ids or any(previous) or any(c.speaker_fixed for c in cues):
        _keep_cast(cues, previous, embeds, reserved_ids)
        info = {}  # Recompute metadata for the final cast rather than the preliminary clusters.

    speakers = speakers_of(cues)
    if not info:
        info = G.speaker_genders(cues, pitches)
    counts: dict[str, int] = {}
    for s in speakers:
        s.update(info[s["id"]])
        g = s["gender"]
        s["age"] = age_of(g, s["f0"])
        counts[g] = counts.get(g, 0) + 1
        name = G.NAMES.get(g, "")
        s["name"] = f"{name} {counts[g]}" if name and method == "voiceprint" else name
    return speakers, method
