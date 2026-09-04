"""Kiểm thử phần gán nhãn nhân vật — logic thuần, không cần cài pyannote."""

from __future__ import annotations

from backend.core.diarize import assign, relabel_by_talktime, speakers_of
from backend.core.subtitles import Cue


def turn(start: float, end: float, speaker: str) -> dict:
    return {"start": start, "end": end, "speaker": speaker}


def cue(start: float, end: float, text: str = "xin chào") -> Cue:
    return Cue(start=start, end=end, text=text)


# ------------------------------------------------------- đánh số lại nhãn


def test_nguoi_noi_nhieu_nhat_thanh_S1():
    turns = [
        turn(0, 1, "SPEAKER_00"),   # tổng 1 s
        turn(1, 9, "SPEAKER_01"),   # tổng 8 s  -> phải là S1
        turn(9, 12, "SPEAKER_02"),  # tổng 3 s  -> S2
    ]
    out = relabel_by_talktime(turns)
    assert [t["speaker"] for t in out] == ["S3", "S1", "S2"]


def test_danh_so_lai_on_dinh_khi_bang_nhau():
    """Hai người nói bằng nhau thì thứ tự vẫn xác định, không đổi giữa các lần."""
    turns = [turn(0, 5, "SPEAKER_01"), turn(5, 10, "SPEAKER_00")]
    first = [t["speaker"] for t in relabel_by_talktime(turns)]
    second = [t["speaker"] for t in relabel_by_talktime(turns)]
    assert first == second


def test_gop_nhieu_luot_cua_cung_mot_nguoi():
    turns = [
        turn(0, 2, "SPEAKER_00"),
        turn(10, 12, "SPEAKER_00"),  # cộng lại 4 s
        turn(2, 5, "SPEAKER_01"),    # 3 s
    ]
    out = relabel_by_talktime(turns)
    assert {t["speaker"] for t in out} == {"S1", "S2"}
    assert out[0]["speaker"] == "S1"  # SPEAKER_00 nói nhiều hơn


# ------------------------------------------------------------- gán nhãn


def test_gan_theo_chong_lan_lon_nhat():
    cues = [cue(0, 2), cue(3, 5)]
    turns = [turn(0, 2.5, "S1"), turn(2.5, 6, "S2")]
    stats = assign(cues, turns)
    assert [c.speaker for c in cues] == ["S1", "S2"]
    assert stats["labeled"] == 2
    assert stats["empty"] == 0
    assert stats["speakers"] == 2


def test_cue_vat_qua_hai_nguoi_lay_ben_chiem_nhieu_hon():
    # cue 0–10; S1 chiếm 0–3 (3 s), S2 chiếm 3–10 (7 s) -> S2 thắng
    cues = [cue(0, 10)]
    turns = [turn(0, 3, "S1"), turn(3, 10, "S2")]
    assign(cues, turns)
    assert cues[0].speaker == "S2"


def test_chong_lan_yeu_van_gan_nhung_bi_danh_dau_can_xem_lai():
    # cue 0–10 nhưng chỉ chồng lấn 2 s -> dưới ngưỡng CONFIDENT_RATIO
    cues = [cue(0, 10)]
    turns = [turn(8, 10, "S1")]
    stats = assign(cues, turns)
    assert cues[0].speaker == "S1", "không được bỏ trống, nếu không cue mất lồng tiếng"
    assert stats["unsure"] == 1


def test_cue_khong_chong_lan_lay_luot_gan_nhat():
    # cue 5.0–5.5; lượt nói kết thúc ở 4.5 -> cách 0.5 s, trong NEAR_WINDOW
    cues = [cue(5.0, 5.5)]
    turns = [turn(0, 4.5, "S1")]
    stats = assign(cues, turns)
    assert cues[0].speaker == "S1"
    assert stats["unsure"] == 1


def test_cue_qua_xa_moi_luot_thi_de_trong():
    cues = [cue(100, 101)]
    turns = [turn(0, 5, "S1")]
    stats = assign(cues, turns)
    assert cues[0].speaker == ""
    assert stats["empty"] == 1
    assert stats["labeled"] == 0


def test_khong_co_luot_nao_thi_moi_cue_deu_trong():
    cues = [cue(0, 1), cue(2, 3)]
    stats = assign(cues, [])
    assert all(c.speaker == "" for c in cues)
    assert stats["empty"] == 2
    assert stats["speakers"] == 0


def test_tieng_noi_chong_lan_chon_nguoi_noi_chinh():
    # hai người cùng nói 3–4; S1 phủ gần hết cue nên phải thắng
    cues = [cue(0, 4)]
    turns = [turn(0, 4, "S1"), turn(3, 4, "S2")]
    assign(cues, turns)
    assert cues[0].speaker == "S1"


def test_danh_sach_cue_rong():
    stats = assign([], [turn(0, 1, "S1")])
    assert stats["total"] == 0


# --------------------------------------------------------- tổng hợp nhân vật


def test_tong_hop_nhan_vat_sap_theo_thoi_gian_noi():
    cues = [
        Cue(0, 1, "một", speaker="S2"),
        Cue(1, 9, "hai", speaker="S1"),
        Cue(9, 10, "ba", speaker="S2"),
    ]
    out = speakers_of(cues)
    assert [s["id"] for s in out] == ["S1", "S2"]
    assert out[0]["seconds"] == 8.0
    assert out[0]["lines"] == 1
    assert out[1]["lines"] == 2
    assert out[1]["seconds"] == 2.0


def test_tong_hop_bo_qua_cue_chua_gan_nhan():
    cues = [Cue(0, 1, "a", speaker=""), Cue(1, 2, "b", speaker="S1")]
    out = speakers_of(cues)
    assert [s["id"] for s in out] == ["S1"]


def test_mau_cau_uu_tien_ban_dich():
    cues = [Cue(0, 1, "原文", text2="bản dịch", speaker="S1")]
    out = speakers_of(cues)
    assert out[0]["sample"] == "bản dịch"
    assert out[0]["first_line"] == 1


# ------------------------------------------------- available() phải nhẹ


def test_available_khong_nap_thu_vien_nang():
    """`/api/system` gọi hàm này mỗi lần mở trang — nạp torch ở đây là treo trang.

    Tác giả gốc đã cố tránh đúng chuyện này cho tính năng nhân bản giọng; test
    này khoá lại để lần sửa sau không vô tình làm hỏng.
    """
    import subprocess
    import sys

    code = (
        "import sys; from backend.core import diarize; diarize.available();"
        "heavy=[m for m in ('torch','pyannote.audio','speechbrain') if m in sys.modules];"
        "print(','.join(heavy))"
    )
    out = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, timeout=120
    )
    assert out.returncode == 0, out.stderr[-500:]
    assert out.stdout.strip() == "", f"available() đã nạp: {out.stdout.strip()}"
