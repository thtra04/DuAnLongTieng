"""Kiểm thử bảng ngôn ngữ dùng chung cho Whisper, Google và NLLB."""

from __future__ import annotations

import pytest

from app.languages import BY_CODE, LANGUAGES, RTL, google_code, name_en, name_vi, nllb_code


def test_moi_ngon_ngu_du_khoa():
    for item in LANGUAGES:
        assert set(item) >= {"code", "vi", "en", "flag", "nllb"}
        assert all(item[k].strip() for k in ("code", "vi", "en", "nllb"))


def test_ma_ngon_ngu_khong_trung():
    codes = [x["code"] for x in LANGUAGES]
    assert len(codes) == len(set(codes))


def test_ma_nllb_dung_dinh_dang_flores():
    for item in LANGUAGES:
        assert "_" in item["nllb"], f"{item['code']} thiếu phần chữ viết"


def test_co_du_ngon_ngu_nhu_README_noi():
    assert len(LANGUAGES) == 41


@pytest.mark.parametrize("code,expected", [("zh", "zh-CN"), ("he", "iw"), ("vi", "vi"), ("en", "en")])
def test_ma_google_co_ngoai_le(code, expected):
    assert google_code(code) == expected


def test_ma_nllb_tra_dung():
    assert nllb_code("vi") == "vie_Latn"
    assert nllb_code("zh") == "zho_Hans"


def test_ma_la_roi_ve_tieng_anh():
    assert nllb_code("khong-co") == "eng_Latn"


def test_ten_tieng_viet():
    assert name_vi("vi") == "Tiếng Việt"
    assert name_vi(None) == "Tự động"
    assert name_vi("xx") == "xx"


def test_ten_tieng_anh():
    assert name_en("vi") == "Vietnamese"
    assert name_en(None) == "auto-detected"


def test_ngon_ngu_phai_sang_trai_deu_co_trong_bang():
    assert RTL <= set(BY_CODE)
