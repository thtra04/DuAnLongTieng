"""Kịch bản lồng tiếng: ghép mảnh dịch thành câu đọc có dấu câu, cho người dùng sửa rồi đọc theo.

Ca thật (job LieuTrai, dịch Google từng dòng): trước đây nối thẳng các mảnh ra
"Đồ ăn và quần áo sang trọng Thật là một giai điệu lớn Đó là trường hợp Gia đình…"
— không chấm phẩy, chữ hoa giữa câu, giọng đọc không có chỗ ngắt nghỉ.
"""

from __future__ import annotations

import numpy as np
import pytest

from backend.core import dubbing
from backend.core.subtitles import Cue


def cue(start, src, vi, spk="S1"):
    return Cue(start=start, end=start + 1.5, text=src, text2=vi, speaker=spk)


def units_of(cues):
    return [u["text"] for u in dubbing.speech_units(cues)]


def test_dong_dich_rieng_viet_hoa_thi_cham_cau():
    cues = [cue(0, "锦衣玉食", "Đồ ăn và quần áo sang trọng"), cue(1.6, "好大的口气", "Thật là một giai điệu lớn")]
    assert units_of(cues) == ["Đồ ăn và quần áo sang trọng. Thật là một giai điệu lớn."]


def test_cau_goc_la_cau_hoi_thi_dau_hoi():
    cues = [cue(0, "你是哪里人", "bạn đến từ đâu"), cue(1.6, "为何深夜独行", "Tại sao lại đi một mình giữa đêm")]
    assert units_of(cues) == ["Bạn đến từ đâu? Tại sao lại đi một mình giữa đêm?"]


def test_ve_phu_noi_bang_dau_phay_va_ha_chu_hoa():
    cues = [cue(0, "若怕受连累", "Nếu bạn sợ bị liên lụy"), cue(1.6, "我现在走便是", "Tôi sắp đi đây")]
    assert units_of(cues) == ["Nếu bạn sợ bị liên lụy, tôi sắp đi đây."]


def test_loi_goi_ngan_thi_dau_phay():
    cues = [cue(0, "老爷", "Lão gia"), cue(1.6, "这是谁", "đây là ai")]
    assert units_of(cues) == ["Lão gia, đây là ai?"]


def test_giu_chu_hoa_cua_ten_rieng_sau_dau_phay():
    cues = [cue(0, "小娘子", "Cô nương"), cue(1.6, "朱大升最会疼人", "Chu Đại Thăng biết thương người nhất")]
    assert units_of(cues) == ["Cô nương, Chu Đại Thăng biết thương người nhất."]


def test_cau_dich_bi_chia_giua_chung_thi_noi_lien():
    # dòng gốc dài bị cắt vì đủ ký tự, bản dịch cả câu chia theo tỉ lệ: mảnh sau viết thường là phần tiếp
    dai = "这些粗茶淡饭奴家可是一口都咽不下去郎君不是说过要让我吃穿不愁"
    assert len(dai) >= dubbing.CJK_CUT_CHARS
    cues = [cue(0, dai, "Những bữa cơm đạm bạc này thiếp một miếng cũng"), cue(1.6, "怎么才一日就变了", "nuốt không trôi.")]
    assert units_of(cues) == ["Những bữa cơm đạm bạc này thiếp một miếng cũng nuốt không trôi."]


def test_dong_goc_ngan_manh_sau_viet_thuong_van_dat_dau():
    # ca thật: Google trả "phớt lờ anh ấy" viết thường dù là vế riêng
    cues = [cue(0, "他不懂事", "Anh ấy là người không biết gì"), cue(1.6, "别理他", "phớt lờ anh ấy")]
    assert units_of(cues) == ["Anh ấy là người không biết gì, phớt lờ anh ấy."]
    cues = [cue(0, "你是哪里人", "Bạn đến từ đâu"), cue(1.6, "为何深夜独行", "tại sao lại đi một mình")]
    assert units_of(cues) == ["Bạn đến từ đâu? Tại sao lại đi một mình?"]


def test_ban_dich_da_co_dau_cau_thi_giu_nguyen():
    cues = [cue(0, "这便对了", "Đúng rồi."), cue(1.6, "有些事知道的越少越安心", "Có những chuyện biết càng ít càng yên tâm.")]
    assert units_of(cues) == ["Đúng rồi. Có những chuyện biết càng ít càng yên tâm."]


def test_mot_dong_cung_viet_hoa_va_cham_het_cau():
    assert units_of([cue(0, "回你屋去", "quay về phòng đi")]) == ["Quay về phòng đi."]
    assert units_of([cue(0, "谁让你进来的", "ai cho ngươi vào")]) == ["Ai cho ngươi vào?"]


def test_doi_nguoi_noi_van_tach_cau():
    cues = [cue(0, "老爷", "Lão gia", "S1"), cue(1.6, "这是谁", "đây là ai", "S2")]
    assert units_of(cues) == ["Lão gia.", "Đây là ai?"]


def test_ban_sua_tay_chi_ap_khi_con_khop():
    cues = [cue(0, "锦衣玉食", "Đồ ăn sang trọng"), cue(1.6, "好大的口气", "Thật là một giai điệu lớn")]
    units = dubbing.speech_units(cues)
    base = units[0]["text"]
    script = [{"cues": [0, 1], "base": base, "text": "cẩm y ngọc thực, khẩu khí lớn thật"}]
    assert dubbing.apply_script(units, script) == 1
    assert units[0]["text"] == "Cẩm y ngọc thực, khẩu khí lớn thật."

    units = dubbing.speech_units(cues)
    stale = [{"cues": [0, 1], "base": "chữ cũ đã đổi", "text": "Không được đọc câu này."}]
    assert dubbing.apply_script(units, stale) == 0, "phụ đề đã đổi sau khi sửa kịch bản thì bỏ bản sửa cũ"
    wrong = [{"cues": [0], "base": base, "text": "Lệch nhóm dòng."}, {"cues": ["x"], "text": "rác"}]
    assert dubbing.apply_script(units, wrong) == 0
    assert units[0]["text"] == base


def test_kich_ban_van_ban_co_moc_gio_va_ten_vai():
    units = [{"start": 59.8, "end": 61, "speaker": "", "text": "Đi thôi."},
             {"start": 65.4, "end": 67.1, "speaker": "S1", "text": "Lão gia, đây là ai?"}]
    assert dubbing.script_text(units, {"S1": "Hoắc Thanh"}) == (
        "Phút 0 · 00:00\n[00:59.800 → 01:01.000] Đi thôi.\n"
        "Phút 1 · 01:00\n[01:05.400 → 01:07.100] Hoắc Thanh: Lão gia, đây là ai?\n")


class GiongGhi:
    """TTS giả: ghi lại chữ được đưa vào đọc."""

    def __init__(self):
        self.read = []

    def infer(self, text, **kw):
        self.read.append(text)
        return 0.05 * np.sin(np.arange(int(0.8 * dubbing.SR)) * 0.03)


def test_long_tieng_doc_dung_kich_ban_da_sua(tmp_path, monkeypatch):
    eng = GiongGhi()
    monkeypatch.setattr(dubbing, "get_engine", lambda: eng)
    cues = [cue(0, "锦衣玉食", "Đồ ăn sang trọng"), cue(1.6, "好大的口气", "Thật là một giai điệu lớn")]
    base = dubbing.speech_units(cues)[0]["text"]
    logs = []
    dubbing.build_dub_track(cues, 4.0, tmp_path, voice="A", on_log=logs.append,
                            script=[{"cues": [0, 1], "base": base, "text": "Cẩm y ngọc thực, khẩu khí lớn thật"}])
    assert eng.read == ["Cẩm y ngọc thực, khẩu khí lớn thật."]
    assert any("kịch bản đã sửa tay cho 1 câu" in ln for ln in logs)
    assert "Cẩm y ngọc thực" in (tmp_path / "kich_ban_long_tieng.txt").read_text(encoding="utf-8")


def test_api_kich_ban_tra_dung_cau_se_doc(studio_client):
    r = studio_client.post("/api/tts/script", json={
        "cues": [c.to_dict() for c in [cue(0, "老爷", "Lão gia"), cue(1.6, "这是谁", "đây là ai")]],
        "shorten": False,
    })
    assert r.status_code == 200
    units = r.json()["units"]
    assert [(u["cues"], u["text"], u["speaker"]) for u in units] == [([0, 1], "Lão gia, đây là ai?", "S1")]
    assert studio_client.post("/api/tts/script", json={"cues": []}).json() == {"units": []}


@pytest.mark.parametrize("text, want", [("Tôi thấy", "tôi thấy"), ("Chu Đại Thăng", "Chu Đại Thăng"), ("AI giỏi", "AI giỏi")])
def test_ha_chu_hoa_dau_manh(text, want):
    assert dubbing._lower_first(text) == want
