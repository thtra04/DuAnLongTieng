"""Kiểm thử phần nối HP-5 vào hệ thống: bộ rút gọn theo engine và bước pipeline."""

from __future__ import annotations

import pytest

from backend.core import translate
from backend.core.pipeline import analyze_steps
from backend.core.translate import make_tightener


# ----------------------------------------------------------- bộ rút gọn


@pytest.mark.parametrize("engine", ["google", "mymemory", "nllb", "khong-co"])
def test_engine_khong_dieu_khien_duoc_do_dai_thi_khong_co_bo_rut_gon(engine):
    assert make_tightener(engine) is None


@pytest.mark.parametrize("engine", ["claude", "openai"])
def test_engine_ai_co_bo_rut_gon(engine):
    assert callable(make_tightener(engine))


def test_bo_rut_gon_gui_dung_dinh_dang_va_doc_lai_ket_qua(monkeypatch):
    seen = {}

    def chat_gia(engine, system, user, api_key, model, base_url):
        seen.update(engine=engine, system=system, user=user, model=model)
        return "1|Ta quyết rồi.\n2|Tuân chỉ."

    monkeypatch.setattr(translate, "_chat", chat_gia)
    tighten = make_tightener("claude", model="claude-sonnet-5", target="vi")
    out = tighten([
        {"text": "Trẫm đã quyết định rồi, không cần bàn thêm nữa.", "target_syllables": 4},
        {"text": "Thần xin tuân theo thánh chỉ.", "target_syllables": 2},
    ])

    assert out == ["Ta quyết rồi.", "Tuân chỉ."]
    assert seen["engine"] == "claude" and seen["model"] == "claude-sonnet-5"
    # mỗi dòng: số thứ tự | số âm tiết tối đa | câu
    assert "1|4|Trẫm đã quyết định rồi" in seen["user"]
    assert "2|2|Thần xin tuân" in seen["user"]
    assert "Vietnamese" in seen["system"]


def test_dong_bi_bo_sot_thi_giu_nguyen_van(monkeypatch):
    monkeypatch.setattr(translate, "_chat", lambda *a, **k: "2|Ngắn.")
    tighten = make_tightener("openai")
    out = tighten([
        {"text": "Câu một dài.", "target_syllables": 2},
        {"text": "Câu hai dài.", "target_syllables": 2},
    ])
    assert out == ["Câu một dài.", "Ngắn."]


def test_ket_qua_dao_thu_tu_van_vao_dung_cau(monkeypatch):
    monkeypatch.setattr(translate, "_chat", lambda *a, **k: "2|B.\n1|A.")
    out = make_tightener("openai")([{"text": "a", "target_syllables": 1}, {"text": "b", "target_syllables": 1}])
    assert out == ["A.", "B."]


def test_loi_api_duoc_day_len_de_vong_lap_dung(monkeypatch):
    def hong(*a, **k):
        raise translate.TranslateError("hết hạn mức")

    monkeypatch.setattr(translate, "_chat", hong)
    with pytest.raises(translate.TranslateError):
        make_tightener("claude")([{"text": "x", "target_syllables": 1}])


# ---------------------------------------------------------- bước pipeline


def keys(cfg):
    return [s.key for s in analyze_steps(cfg)]


def test_buoc_ngan_sach_chi_co_khi_bat_vong_lap():
    assert "budget" in keys({"sub_mode": "auto", "translate": True, "budget_loop": True})
    assert "budget" not in keys({"sub_mode": "auto", "translate": True})


def test_khong_dich_thi_khong_co_buoc_ngan_sach():
    """Vòng lặp siết bản dịch — không dịch thì không có gì để siết."""
    assert "budget" not in keys({"sub_mode": "auto", "budget_loop": True})


def test_buoc_ngan_sach_nam_sau_dich_truoc_ghi_file():
    ks = keys({"sub_mode": "auto", "translate": True, "budget_loop": True})
    assert ks.index("translate") < ks.index("budget") < ks.index("write")
