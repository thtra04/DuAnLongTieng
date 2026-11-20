"""Kiểm thử tách nhiều người cùng giới theo véc-tơ giọng và đoán nhóm tuổi (voiceprint.py)."""

from __future__ import annotations

import numpy as np

from backend.core import voiceprint
from backend.core.subtitles import Cue


def _unit(v):
    v = np.asarray(v, dtype=np.float64)
    return v / np.linalg.norm(v)


def test_age_of_tre_em_theo_cao_do_va_gioi():
    assert voiceprint.age_of("M", 120) == "A"
    assert voiceprint.age_of("M", 230) == "C"      # bé trai
    assert voiceprint.age_of("F", 220) == "A"
    assert voiceprint.age_of("F", 320) == "C"
    assert voiceprint.age_of("", 300) == ""        # chưa biết giới thì không đoán
    assert voiceprint.age_of("M", 0) == ""


def test_cluster_tach_hai_nguoi_va_gop_cung_nguoi():
    rng = np.random.default_rng(0)
    a, b = _unit([1, 0, 0, 0]), _unit([0, 1, 0, 0])
    vecs = np.stack([_unit(a + 0.05 * rng.normal(size=4)) for _ in range(4)]
                    + [_unit(b + 0.05 * rng.normal(size=4)) for _ in range(4)])
    lab = voiceprint.cluster(vecs, np.ones(8))
    assert len(set(lab[:4])) == 1 and len(set(lab[4:])) == 1 and lab[0] != lab[7]
    assert voiceprint.cluster(np.zeros((0, 4)), np.zeros(0)) == []


def _cues(n, dur=5.0):
    return [Cue(start=i * 6.0, end=i * 6.0 + dur, text="x") for i in range(n)]


def _pitch(f0):
    return {"f0": f0, "voiced": 50}


def test_split_hai_nam_mot_nu_khac_nhau():
    m1, m2, f1 = _unit([1, 0, 0, 0]), _unit([0, 1, 0, 0]), _unit([0, 0, 1, 0])
    # 4 câu m1 (nam), 3 câu m2 (nam), 2 câu f1 (nữ)
    embeds = [m1] * 4 + [m2] * 3 + [f1] * 2
    pitches = [_pitch(110)] * 7 + [_pitch(220)] * 2
    cues = _cues(9)
    st = voiceprint.split_speakers(cues, embeds, pitches)
    labels = [c.speaker for c in cues]
    assert len(set(labels[:4])) == 1 and len(set(labels[4:7])) == 1
    assert labels[0] != labels[4] != labels[7]
    kinds = {k: v["gender"] for k, v in st["speakers"].items()}
    assert sorted(kinds.values()) == ["F", "M", "M"]
    assert st["labeled"] == 9 and st["empty"] == 0
    # nhãn S1 là người nói nhiều nhất
    assert cues[0].speaker == "S1"


def test_cue_ngan_khong_co_vec_to_theo_cum_cung_gioi():
    m1, m2 = _unit([1, 0, 0, 0]), _unit([0, 1, 0, 0])
    embeds = [m1] * 4 + [m2] * 3 + [None]
    pitches = [_pitch(110)] * 8
    cues = _cues(8)
    voiceprint.split_speakers(cues, embeds, pitches)
    assert cues[7].speaker != ""                   # có cao độ -> gán vào một cụm nam
    # không cao độ, không véc-tơ -> để trống
    cues2 = _cues(8)
    pitches2 = pitches[:7] + [_pitch(0)]
    voiceprint.split_speakers(cues2, embeds, pitches2)
    assert cues2[7].speaker == ""


def test_cum_qua_it_tieng_don_vao_cum_gan():
    m1, m2 = _unit([1, 0, 0, 0]), _unit([0, 1, 0, 0])
    embeds = [m1] * 5 + [m2]
    pitches = [_pitch(110)] * 6
    cues = _cues(6)
    cues[5].end = cues[5].start + 1.5             # chỉ 1,5 giây < MIN_CLUSTER_S
    voiceprint.split_speakers(cues, embeds, pitches)
    assert len({c.speaker for c in cues}) == 1


def test_gioi_han_so_nguoi_moi_gioi():
    n = 9
    embeds = [_unit(np.eye(10)[i]) for i in range(n)]
    cues = _cues(n)
    st = voiceprint.split_speakers(cues, embeds, [_pitch(110)] * n)
    assert len(st["speakers"]) <= voiceprint.MAX_PER_GENDER


def test_nguong_thich_nghi_theo_do_sach_cua_thoai():
    rng = np.random.default_rng(1)
    base = _unit([1, 0, 0, 0, 0, 0])
    clean = np.stack([_unit(base + 0.05 * rng.normal(size=6)) for _ in range(8)])
    noisy = np.stack([_unit(base + 1.2 * rng.normal(size=6)) for _ in range(8)])
    assert voiceprint.adaptive_merge_sim(clean) > voiceprint.adaptive_merge_sim(noisy)
    lo, hi = voiceprint.MIN_MERGE, voiceprint.MAX_MERGE
    assert lo <= voiceprint.adaptive_merge_sim(noisy) <= hi
    assert voiceprint.adaptive_merge_sim(clean[:2]) == voiceprint.MERGE_SIM


def test_nam_quat_to_khong_thanh_vai_nu():
    """Ca thật (trích đoạn LieuTrai): nam chính quát lên 205–220 Hz bị chia sang nhóm nữ thành vai "Nữ 2".
    Véc-tơ giọng vẫn giống nam chính hơn hẳn giống nữ -> phải gộp về nam chính."""
    rng = np.random.default_rng(3)
    m, f = _unit([1, 0, 0, 0, 0]), _unit([0, 1, 0, 0, 0])
    noisy = lambda v: _unit(v + 0.08 * rng.normal(size=5))  # noqa: E731
    embeds = [noisy(m) for _ in range(6)] + [noisy(f) for _ in range(5)] + [noisy(m) for _ in range(2)]
    pitches = [_pitch(120)] * 6 + [_pitch(240)] * 5 + [_pitch(215)] * 2
    cues = _cues(13)
    st = voiceprint.split_speakers(cues, embeds, pitches)
    labels = [c.speaker for c in cues]
    assert labels[11] == labels[12] == labels[0], "câu nam quát to phải về vai nam chính"
    assert len(st["speakers"]) == 2
    assert {v["gender"] for v in st["speakers"].values()} == {"M", "F"}


def test_cau_ngan_gan_theo_vec_to_khong_theo_cao_do():
    m, f = _unit([1, 0, 0, 0]), _unit([0, 1, 0, 0])
    embeds = [m] * 4 + [f] * 4 + [m]
    pitches = [_pitch(120)] * 4 + [_pitch(240)] * 4 + [_pitch(240)]  # câu ngắn cao giọng
    cues = _cues(9)
    cues[8].end = cues[8].start + 0.6  # ngắn hơn MIN_EMBED_S nhưng đủ MIN_ASSIGN_S
    voiceprint.split_speakers(cues, embeds, pitches)
    assert cues[8].speaker == cues[0].speaker


def test_cum_nho_so_voi_tong_thoai_bi_don():
    """Video dài: cụm 5 giây trên 400 giây thoại (dưới 1,5 %) là vai ma -> dồn vào cụm gần nhất."""
    a, b = _unit([1, 0.2, 0, 0]), _unit([0.2, 1, 0, 0])
    n = 80
    embeds = [a] * n + [b]
    cues = _cues(n + 1)
    st = voiceprint.split_speakers(cues, embeds, [_pitch(120)] * (n + 1))
    assert len(st["speakers"]) == 1
    assert voiceprint.MIN_CLUSTER_FRAC * 405 > voiceprint.MIN_CLUSTER_S
