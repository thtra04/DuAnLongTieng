"""Kiểm thử định tuyến giọng: mỗi nhân vật phải được đọc bằng đúng giọng của mình.

Đây là bài kiểm tra quan trọng nhất của tính năng lồng tiếng đa nhân vật. Nếu
định tuyến sai thì cả phim vẫn ra tiếng bình thường, không có lỗi nào bung ra,
log vẫn báo thành công — chỉ là mọi vai đọc chung một giọng. Loại hỏng im lặng
đó chỉ có test mới bắt được.

Không gọi TTS thật: thay engine bằng một bản giả ghi lại từng lần được gọi.
"""

from __future__ import annotations

import numpy as np
import pytest

from app import dubbing
from app.subtitles import Cue


class FakeEngine:
    """Engine giả — ghi lại mọi lần `infer` để kiểm tra định tuyến."""

    def __init__(self, seconds: float = 0.4):
        self.calls: list[dict] = []
        self.seconds = seconds

    def infer(self, text: str, **kwargs):
        self.calls.append({"text": text, **kwargs})
        n = int(self.seconds * dubbing.SR)
        # nhiễu nhẹ chứ không phải im lặng: im lặng sẽ bị _trim_silence cắt sạch
        rng = np.random.default_rng(len(self.calls))
        return (rng.random(n, dtype=np.float32) - 0.5) * 0.2

    def voices_used(self) -> list[str]:
        return [c.get("voice", "") for c in self.calls]

    def refs_used(self) -> list[str]:
        return [c.get("ref_audio", "") for c in self.calls]


@pytest.fixture
def engine(monkeypatch):
    fake = FakeEngine()
    monkeypatch.setattr(dubbing, "get_engine", lambda: fake)
    return fake


def c(start, end, text, speaker="", text2=None):
    return Cue(start=start, end=end, text=text, text2=text2 if text2 is not None else text,
               speaker=speaker)


def build(cues, workdir, **kw):
    return dubbing.build_dub_track(
        cues, total_duration=cues[-1].end + 1, workdir=workdir, **kw
    )


# ------------------------------------------------------- định tuyến giọng


def test_moi_nhan_vat_mot_giong(engine, workdir):
    cues = [
        c(0.0, 2.0, "Ta là hoàng đế.", "S1"),
        c(3.0, 5.0, "Thần tuân lệnh.", "S2"),
        c(6.0, 8.0, "Trẫm đã quyết.", "S1"),
    ]
    build(cues, workdir, voice="mac_dinh",
          voice_map={"S1": "giong_nam_bac", "S2": "giong_nu_nam"})

    assert engine.voices_used() == ["giong_nam_bac", "giong_nu_nam", "giong_nam_bac"]


def test_cue_khong_co_nhan_dung_giong_chung(engine, workdir):
    cues = [c(0.0, 2.0, "Lời dẫn chuyện."), c(3.0, 5.0, "Ta đây.", "S1")]
    build(cues, workdir, voice="giong_dan", voice_map={"S1": "giong_vai"})

    assert engine.voices_used() == ["giong_dan", "giong_vai"]


def test_nhan_vat_thieu_trong_bang_thi_roi_ve_giong_chung(engine, workdir):
    cues = [c(0.0, 2.0, "Một.", "S1"), c(3.0, 5.0, "Hai.", "S9")]
    build(cues, workdir, voice="giong_chung", voice_map={"S1": "giong_rieng"})

    assert engine.voices_used() == ["giong_rieng", "giong_chung"]


def test_mau_nhan_ban_uu_tien_hon_giong_dung_san(engine, workdir):
    cues = [c(0.0, 2.0, "Ta đây.", "S1"), c(3.0, 5.0, "Thần đây.", "S2")]
    build(cues, workdir, voice="chung",
          voice_map={"S1": "khong_duoc_dung", "S2": "giong_dung_san"},
          ref_map={"S1": "/tmp/ref_S1.wav"})

    assert engine.refs_used() == ["/tmp/ref_S1.wav", ""]
    # S1 đi bằng mẫu nhân bản nên KHÔNG được truyền kèm `voice`
    assert "voice" not in engine.calls[0]
    assert engine.calls[1]["voice"] == "giong_dung_san"


def test_nhan_ban_bat_denoise(engine, workdir):
    cues = [c(0.0, 2.0, "Ta đây.", "S1")]
    build(cues, workdir, ref_map={"S1": "/tmp/ref.wav"})
    assert engine.calls[0]["denoise"] is True


# ----------------------------------------- không trộn hai vai vào một lần đọc


def test_hai_vai_doi_dap_khong_bi_doc_chung_mot_lan(engine, workdir):
    """Hai cue liền nhau, cùng một câu về mặt ngữ pháp, nhưng khác người nói."""
    cues = [c(0.0, 1.0, "Anh đi đâu", "S1"), c(1.0, 2.0, "đấy?", "S2")]
    build(cues, workdir, voice_map={"S1": "giong_a", "S2": "giong_b"})

    assert len(engine.calls) == 2, "gộp chung là mất hẳn ý nghĩa tách vai"
    assert engine.voices_used() == ["giong_a", "giong_b"]


def test_cung_mot_vai_van_duoc_gop_de_doc_tron_cau(engine, workdir):
    cues = [c(0.0, 1.0, "Hôm nay", "S1"), c(1.0, 2.0, "trời đẹp.", "S1")]
    build(cues, workdir, voice_map={"S1": "giong_a"})

    assert len(engine.calls) == 1, "cùng một người thì phải đọc trọn câu, không cắt vụn"
    assert "Hôm nay trời đẹp." in engine.calls[0]["text"]


# ------------------------------------------------------------- thống kê


def test_thong_ke_dem_du_so_cau(engine, workdir):
    cues = [c(0.0, 2.0, "Một.", "S1"), c(3.0, 5.0, "Hai.", "S2")]
    _, stats = build(cues, workdir, voice_map={"S1": "a", "S2": "b"})

    assert stats["count"] == 2
    assert stats["failed"] == 0
    assert stats["units"] == 2


def test_track_duoc_ghi_ra_file(engine, workdir):
    cues = [c(0.0, 2.0, "Một.", "S1")]
    path, _ = build(cues, workdir, voice_map={"S1": "a"})

    assert path.exists() and path.name == "dub.wav"
    assert path.stat().st_size > 1000


def test_khong_con_thu_muc_tam_sau_khi_xong(engine, workdir):
    cues = [c(0.0, 2.0, "Một.", "S1")]
    build(cues, workdir, voice_map={"S1": "a"})
    assert not (workdir / "tts_tmp").exists(), "phải dọn thư mục tạm"


# ------------------------------------------------- hành vi cũ không đổi


def test_khong_truyen_bang_gi_thi_chay_y_nhu_truoc(engine, workdir):
    """Video một giọng / chưa bật nhận diện -> vẫn dùng đúng một giọng chung."""
    cues = [c(0.0, 2.0, "Một."), c(3.0, 5.0, "Hai."), c(6.0, 8.0, "Ba.")]
    build(cues, workdir, voice="giong_duy_nhat")

    assert set(engine.voices_used()) == {"giong_duy_nhat"}
