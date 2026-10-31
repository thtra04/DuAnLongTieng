"""Kiểm thử bộ rút gọn câu tiếng Việt bằng luật (HP-5, cấu hình không có AI)."""

from __future__ import annotations

import pytest

from backend.core import budget, shorten
from backend.core.duration import syllables
from backend.core.shorten import make_tightener
from backend.core.subtitles import Cue


def test_cau_da_vua_thi_khong_dong_toi():
    assert shorten.shorten("Tôi rất mệt.", 10) == ("Tôi rất mệt.", 0)


@pytest.mark.parametrize(
    "goc, mong",
    [
        ("Bởi vì trời mưa.", "Vì trời mưa."),
        ("Tuy nhiên, tôi vẫn đi.", "Nhưng, tôi vẫn đi."),
        ("Làm thế nào để về nhà?", "Làm sao để về nhà?"),
        ("Hãy để mọi người tập hợp ngày hôm nay.", "Để mọi người tập hợp hôm nay."),
        ("Tất cả mọi người đều biết.", "Mọi người đều biết."),
        ("Tôi cực kỳ trung thành.", "Tôi rất trung thành."),
    ],
)
def test_tang_1_thay_cum_dai_bang_cum_ngan_cung_nghia(goc, mong):
    # Đích đúng bằng số âm tiết mong muốn: tầng 1 đủ thì không sang tầng sau
    assert shorten.shorten(goc, syllables(mong)) == (mong, 1)


def test_rut_gon_tung_manh_giu_ranh_gioi_cue():
    pieces = ["Bởi vì tôi rất là mệt,", "nên tôi về nhà ngay lập tức nhé."]
    new, tier = shorten.shorten_pieces(pieces, 9)
    assert len(new) == 2 and new[0].startswith("Vì tôi") and new[1].startswith("nên tôi về nhà")
    assert sum(syllables(p) for p in new) <= 10 and tier >= 1


def test_bo_siet_tra_tung_manh_khi_cau_nam_tren_nhieu_cue():
    t = make_tightener()
    out = t([{"text": "Bởi vì trời mưa nên tôi ở nhà.", "target_syllables": 6,
              "pieces": ["Bởi vì trời mưa", "nên tôi ở nhà."]}])
    assert out == [["Vì trời mưa", "nên tôi ở nhà."]]


def test_tang_1_giu_nguyen_khi_chi_can_mot_luat():
    # Đích 3 âm tiết: "Vì trời mưa." vừa đủ nên không đi tiếp sang tầng sau
    assert shorten.shorten("Bởi vì trời mưa.", 3) == ("Vì trời mưa.", 1)


def test_tu_dem_chi_bo_o_dau_cau():
    new, _ = shorten.shorten("Thực ra, người này tôi biết.", 4)
    assert new == "Người này tôi biết."          # "này" sau "người" không phải từ đệm
    new, _ = shorten.shorten("Anh đi được không? Thực ra tôi không muốn.", 6)
    assert new == "Anh đi được không? Tôi không muốn."


def test_tro_tu_cuoi_cau_bi_bo_nhung_dai_tu_thi_giu():
    new, _ = shorten.shorten("Tôi biết điều đó. Đợi chút nhé!", 6)
    assert new == "Tôi biết điều đó. Đợi chút!"


def test_rang_chi_bo_sau_dong_tu_noi_nghi():
    new, _ = shorten.shorten("Tôi biết rằng anh ấy đã đi rồi.", 5)
    assert "rằng" not in new and "đã" not in new
    assert new.startswith("Tôi biết anh ấy")


def test_cua_bo_truoc_dai_tu():
    assert shorten.shorten("Cha của bạn đến.", 3)[0] == "Cha bạn đến."
    assert shorten.shorten("Gia đình của chúng tôi.", 4)[0] == "Gia đình chúng tôi."


def test_khong_bao_gio_cat_y_khi_het_luat():
    goc = "Hà Nội Sài Gòn Đà Nẵng Huế Cần Thơ."
    new, tier = shorten.shorten(goc, 2)
    assert new == goc and tier == 0


def test_viet_hoa_lai_chu_dau_cau():
    new, _ = shorten.shorten("hãy cẩn thận. hãy đi đi.", 3)
    assert new[0].isupper()
    assert ". Đ" in new or ". đ" not in new


def test_khong_doi_ten_rieng_hoa_thuong():
    # "Rất" ở tên riêng không có, nhưng chữ hoa của tên phải giữ
    new, _ = shorten.shorten("Long Vương Tây Hải rất vĩ đại.", 4)
    assert new == "Long Vương Tây Hải vĩ đại."


def test_bo_siet_tra_dung_so_cau_va_ghi_log():
    log: list[str] = []
    t = make_tightener(on_log=log.append)
    out = t(
        [
            {"text": "Bởi vì tôi rất là mệt nhé.", "target_syllables": 3},
            {"text": "Ổn.", "target_syllables": 1},
        ]
    )
    assert out == ["Vì tôi mệt.", "Ổn."]
    assert log and "luật" in log[0]


def test_lam_viec_voi_vong_lap_ngan_sach():
    """Chạy trọn `budget.run_loop` với bộ luật: câu vượt phải ngắn đi, câu vừa giữ nguyên."""

    class MoHinh(budget.duration.DurationModel):
        def __init__(self):
            super().__init__(weights=[1.0], meta={})

        def predict(self, text, voice=""):
            return syllables(text) * 0.25

    cues = [
        Cue(start=0.0, end=1.0, text="a.", text2="Bởi vì tôi rất là mệt nhé."),   # 7 âm > 4 âm ngân sách
        Cue(start=1.0, end=5.0, text="b.", text2="Tôi ổn."),
    ]
    stats = budget.run_loop(cues, make_tightener(), MoHinh())
    assert stats["over_before"] == 1 and stats["tightened"] == 1
    assert cues[0].text2 == "Vì tôi mệt."
    assert cues[1].text2 == "Tôi ổn."
    assert stats["over_after"] == 0
