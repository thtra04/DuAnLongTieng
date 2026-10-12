"""Kiểm thử tách giọng nam / nữ theo cao độ (backend/core/gender.py) và phần nối
vào pipeline, bảng nhân vật, danh sách giọng."""

from __future__ import annotations

import wave

import numpy as np
import pytest

from backend.core import gender
from backend.core.pipeline import analyze_steps
from backend.core.subtitles import Cue
from backend.store import characters

SR = 16000


def _voice(f0: float, seconds: float, amp: float = 0.3) -> np.ndarray:
    """Tiếng "giọng người" giả: sóng cơ bản f0 cùng vài hoạ âm yếu dần."""
    t = np.arange(int(seconds * SR)) / SR
    x = sum(np.sin(2 * np.pi * f0 * k * t) / k for k in range(1, 6))
    return (amp * x / np.abs(x).max()).astype(np.float32)


def _write_wav(path, x: np.ndarray) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((np.clip(x, -1, 1) * 32767).astype("<i2").tobytes())


# ------------------------------------------------------------------ cao độ


@pytest.mark.parametrize("f0", [95.0, 120.0, 150.0, 190.0, 230.0, 300.0])
def test_do_dung_cao_do_cua_giong_gia(f0):
    got = gender.frame_pitches(_voice(f0, 1.0), SR)
    assert got.size > 50
    assert abs(float(np.median(got)) - f0) / f0 < 0.03


def test_giong_tram_khong_bi_nhan_len_mot_quang_tam():
    """Không chia cho tự tương quan của cửa sổ thì 90 Hz hay bị đọc thành 180 Hz."""
    got = gender.frame_pitches(_voice(90.0, 1.0), SR)
    assert float(np.median(got)) < 100


def test_im_lang_va_tieng_on_khong_co_khung_huu_thanh():
    assert gender.frame_pitches(np.zeros(SR, dtype=np.float32), SR).size == 0
    noise = np.random.default_rng(1).normal(0, 0.1, SR).astype(np.float32)
    assert gender.frame_pitches(noise, SR).size < gender.MIN_VOICED
    assert gender.frame_pitches(np.zeros(10, dtype=np.float32), SR).size == 0


def test_gender_of_theo_nguong():
    assert gender.gender_of(120) == "M"
    assert gender.gender_of(gender.SPLIT_HZ) == "F"
    assert gender.gender_of(220) == "F"
    assert gender.gender_of(0) == ""
    assert gender.gender_of(None) == ""


# ------------------------------------------------------------------ đo cue


@pytest.fixture
def wav(tmp_path):
    """0–1 s giọng nam, 1–2 s giọng nữ, 2–3 s im lặng, 3–5 s giọng nữ."""
    x = np.concatenate([_voice(118, 1), _voice(225, 1), np.zeros(SR, np.float32), _voice(240, 2)])
    path = tmp_path / "audio.wav"
    _write_wav(path, x)
    return path


def _cues():
    return [Cue(0.05, 0.95, "a"), Cue(1.05, 1.95, "b"), Cue(2.1, 2.9, "c"), Cue(3.1, 4.9, "d")]


def test_measure_doc_dung_khoang_cua_tung_cue(wav):
    p = gender.measure(wav, _cues())
    assert [gender.gender_of(x["f0"]) for x in p] == ["M", "F", "", "F"]
    assert abs(p[0]["f0"] - 118) < 5 and abs(p[1]["f0"] - 225) < 8
    assert p[2] == {"f0": 0.0, "voiced": 0}


def test_measure_cue_ngoai_file_hoac_qua_ngan_thi_bo(wav):
    p = gender.measure(wav, [Cue(9.0, 10.0, "ngoài file"), Cue(0.5, 0.51, "quá ngắn")])
    assert p == [{"f0": 0.0, "voiced": 0}, {"f0": 0.0, "voiced": 0}]


def test_split_cues_nhom_noi_nhieu_hon_la_s1(wav):
    cues = _cues()
    stats = gender.split_cues(cues, gender.measure(wav, cues))
    # nữ nói 0,9 + 1,8 giây > nam 0,9 giây -> nữ là S1
    assert [c.speaker for c in cues] == ["S2", "S1", "", "S1"]
    f0 = stats.pop("f0")
    assert stats == {"total": 4, "labeled": 3, "empty": 1, "genders": {"S1": "F", "S2": "M"}}
    assert abs(f0["S2"] - 118) < 5 and 215 < f0["S1"] < 250, "cao độ từng nhóm để chọn giọng gần nhất"


def test_split_cues_chi_co_mot_gioi(wav):
    cues = [Cue(1.05, 1.95, "b"), Cue(3.1, 4.9, "d")]
    stats = gender.split_cues(cues, gender.measure(wav, cues))
    assert [c.speaker for c in cues] == ["S1", "S1"]
    assert stats["genders"] == {"S1": "F"}


def test_split_cues_khong_nghe_ra_gi():
    cues = [Cue(0, 1, "a")]
    stats = gender.split_cues(cues, [{"f0": 0.0, "voiced": 0}])
    assert cues[0].speaker == "" and stats["genders"] == {} and stats["empty"] == 1


def test_speaker_genders_gop_theo_nhan_co_trong_so():
    """Một tiếng hét ngắn cao giọng không lật được giới tính của cả nhân vật."""
    cues = [Cue(0, 3, "a", speaker="S1"), Cue(3, 3.4, "b", speaker="S1"),
            Cue(4, 6, "c", speaker="S2"), Cue(7, 8, "d", speaker="S3"), Cue(9, 10, "e")]
    pitches = [{"f0": 120.0, "voiced": 200}, {"f0": 260.0, "voiced": 20},
               {"f0": 215.0, "voiced": 150}, {"f0": 0.0, "voiced": 3}, {"f0": 130.0, "voiced": 90}]
    got = gender.speaker_genders(cues, pitches)
    assert got["S1"] == {"gender": "M", "f0": 120.0}
    assert got["S2"]["gender"] == "F"
    assert got["S3"] == {"gender": "", "f0": 0.0}
    assert set(got) == {"S1", "S2", "S3"}


# --------------------------------------------------------------- chọn giọng


VOICES = [
    {"id": "Minh Đức", "label": "Minh Đức — Nam · Bắc · Phong cách tin tức"},
    {"id": "Xuân Vĩnh", "label": "Xuân Vĩnh — Nam · Nam · Phong cách tự nhiên"},
    {"id": "Trúc Ly", "label": "Trúc Ly — Nữ · Bắc · Phong cách tự nhiên"},
    {"id": "la", "label": "Giọng lạ"},
]


def test_voice_gender_doc_tu_nhan():
    assert [gender.voice_gender(v["label"]) for v in VOICES] == ["M", "M", "F", ""]
    # "Nam" thứ hai là vùng miền, không phải giới tính
    assert gender.voice_gender("Lan — Nữ · Nam · Kể chuyện") == "F"
    assert gender.voice_gender("") == ""


def test_pick_voice_dung_gioi_uu_tien_giong_chua_dung():
    assert gender.pick_voice(VOICES, "M") == "Minh Đức"
    assert gender.pick_voice(VOICES, "M", {"Minh Đức"}) == "Xuân Vĩnh"
    assert gender.pick_voice(VOICES, "M", {"Minh Đức", "Xuân Vĩnh"}) == "Minh Đức"  # hết thì dùng lại
    assert gender.pick_voice(VOICES, "F") == "Trúc Ly"
    assert gender.pick_voice(VOICES, "") == ""
    assert gender.pick_voice([VOICES[3]], "F") == ""


# ------------------------------------------------------------ nối vào hệ thống


def test_buoc_gender_chi_co_khi_bat():
    base = {"source_type": "file", "sub_mode": "auto"}
    assert "gender" not in [s.key for s in analyze_steps(base)]
    keys = [s.key for s in analyze_steps({**base, "gender_split": True, "diarize": True, "translate": True})]
    assert keys.index("diarize") < keys.index("gender") < keys.index("translate")


class _Log:
    def __init__(self):
        self.lines = []

    def log(self, s):
        self.lines.append(s)


def _fill(monkeypatch, voice_map, present, voice="", known=None):
    from backend.core import dubbing, pipeline

    monkeypatch.setattr(dubbing, "list_voices", lambda: [
        {**v, "gender": gender.voice_gender(v["label"])} for v in VOICES
    ])
    monkeypatch.setattr(pipeline.characters, "list_for", lambda job: [
        {"label": k, "gender": g} for k, g in (known or {}).items()
    ])
    pipeline._fill_voices_by_gender(_Log(), {"source_job": "j"}, voice, voice_map, set(present))
    return voice_map


def test_xuat_tu_gan_giong_dung_gioi_cho_vai_chua_chon(monkeypatch):
    got = _fill(monkeypatch, {}, ["S1", "S2", "S3"], known={"S1": "F", "S2": "M", "S3": "M"})
    assert got == {"S1": "Trúc Ly", "S2": "Minh Đức", "S3": "Xuân Vĩnh"}, "hai vai nam không trùng giọng"


def test_xuat_khong_dong_vao_giong_nguoi_dung_da_chon(monkeypatch):
    got = _fill(monkeypatch, {"S1": "Minh Đức"}, ["S1", "S2"], known={"S1": "F", "S2": "M"})
    assert got == {"S1": "Minh Đức", "S2": "Xuân Vĩnh"}, "giữ lựa chọn của người dùng, vai còn lại tránh giọng đã dùng"


def test_xuat_vai_chua_ro_gioi_hoac_giong_chung_la_nhan_ban_thi_bo_qua(monkeypatch):
    assert _fill(monkeypatch, {}, ["S1"], known={"S1": ""}) == {}
    assert _fill(monkeypatch, {}, ["S1"], voice="__clone__", known={"S1": "F"}) == {}


def test_bang_nhan_vat_luu_gioi_tinh_va_ten_goi_y(tmp_db):
    out = characters.sync("job1", [
        {"id": "S1", "seconds": 9, "gender": "F", "name": "Nữ", "f0": 231.4},
        {"id": "S2", "seconds": 4, "gender": "m", "name": "Nam"},
        {"id": "S3", "seconds": 1, "gender": "khác"},
    ])
    assert [(c["label"], c["gender"], c["name"]) for c in out] == [("S1", "F", "Nữ"), ("S2", "M", "Nam"), ("S3", "", "")]
    assert out[0]["f0"] == 231.4

    # Người dùng đổi tên và sửa giới tính; chạy lại phân tích không được ghi đè tên,
    # và kết quả đoán "không rõ" không được xoá giới tính hay cao độ đã có.
    characters.update("job1", "S1", name="Hoắc nương", gender="M")
    out = characters.sync("job1", [{"id": "S1", "seconds": 9, "gender": "", "name": "Nữ"}])
    assert out == [{"label": "S1", "name": "Hoắc nương", "seconds": 9.0, "gender": "M", "f0": 231.4,
                    "voice": "", "style": "", "ref_path": ""}]

    assert characters.update("job1", "S1", gender="x")["gender"] == ""
