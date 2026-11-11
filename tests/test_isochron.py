"""HP-4 — token ngân sách `<len:n>` và việc nối adapter LoRA của NLLB vào app.

Không test nào ở đây nạp torch hay mô hình thật: phần nặng (`_load_nllb`,
`_translate_nllb`) được thay bằng hàm giả, chỉ kiểm tra phần dây nối.
"""

from __future__ import annotations

import pytest

from backend.core import budget, isochron, translate
from backend.core.subtitles import Cue


def test_token_ngan_sach_kep_trong_khoang_1_den_60():
    assert isochron.budget_token(12) == "<len:12>"
    assert isochron.budget_token(0) == "<len:1>"
    assert isochron.budget_token(999) == f"<len:{isochron.BUDGET_MAX}>"
    toks = isochron.all_budget_tokens()
    assert len(toks) == len(set(toks)) == isochron.BUDGET_MAX


def test_gan_token_vao_dau_cau_nguon():
    assert isochron.with_budget("我们获胜了", 5) == "<len:5> 我们获胜了"
    assert isochron.with_budget("我们获胜了", None) == "我们获胜了"
    assert isochron.with_budget("我们获胜了", 0) == "我们获胜了"


def test_mau_huan_luyen_lay_ngan_sach_tu_cau_dich():
    ex = isochron.to_example("我们获胜了", "Chúng ta đã thắng rồi")
    assert ex == {"src": "<len:5> 我们获胜了", "tgt": "Chúng ta đã thắng rồi"}
    assert isochron.to_example("我们获胜了", "Thắng rồi", keep_budget=False)["src"] == "我们获胜了"


def test_chi_coi_la_co_adapter_khi_co_file_cau_hinh(tmp_path):
    assert not isochron.has_adapter(tmp_path)
    d = isochron.adapter_dir(tmp_path)
    d.mkdir()
    assert not isochron.has_adapter(tmp_path), "thư mục rỗng (đang huấn luyện dở) chưa phải adapter"
    (d / "adapter_config.json").write_text("{}", encoding="utf-8")
    assert isochron.has_adapter(tmp_path)


def test_adapter_chi_ap_cho_trung_sang_viet():
    assert translate.lora_applies("zh", "vi")
    assert not translate.lora_applies("en", "vi")
    assert not translate.lora_applies("zh", "en")
    assert not translate.lora_applies(None, "vi")


def test_tat_adapter_bang_bien_moi_truong(monkeypatch, tmp_path):
    from backend import config

    d = isochron.adapter_dir(tmp_path)
    d.mkdir()
    (d / "adapter_config.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(config, "MODEL_DIR", tmp_path)
    monkeypatch.setenv("VSUB_NLLB_LORA", "0")
    assert not translate.lora_available()


def test_khong_co_adapter_thi_khong_dung_lora(monkeypatch, tmp_path):
    from backend import config

    monkeypatch.setattr(config, "MODEL_DIR", tmp_path)
    assert not translate.lora_available()
    # và bộ siết của engine nllb vẫn là bộ luật rút gọn như trước
    assert callable(translate.make_tightener("nllb", target="vi", source="zh"))


def test_dau_vao_nllb_gan_token_va_thay_cau_rong():
    assert translate._nllb_inputs(["你好", "  "], [3, None]) == ["<len:3> 你好", "…"]
    assert translate._nllb_inputs(["你好"]) == ["你好"]


@pytest.fixture
def co_adapter(monkeypatch):
    monkeypatch.setattr(translate, "lora_available", lambda: True)


def test_bo_siet_nllb_dich_lai_voi_token_ngan_sach(monkeypatch, co_adapter):
    calls = []

    def fake(texts, source, target, on_progress=None, on_log=None, budgets=None):
        calls.append((list(texts), source, target, list(budgets)))
        return ["Ta thắng rồi", "Một bản dịch lại còn dài hơn cả bản cũ nữa cơ"]

    monkeypatch.setattr(translate, "_translate_nllb", fake)
    tighten = translate.make_tightener("nllb", target="vi", source="zh")
    out = tighten([
        {"text": "Chúng ta đã giành được chiến thắng rồi", "source": "我们获胜了", "target_syllables": 4, "pieces": ["Chúng ta đã giành được chiến thắng rồi"]},
        {"text": "Đi thôi nào", "source": "走吧", "target_syllables": 2, "pieces": ["Đi thôi nào"]},
    ])
    assert calls == [(["我们获胜了", "走吧"], "zh", "vi", [4, 2])]
    assert out[0] == "Ta thắng rồi"
    assert "dài hơn" not in str(out[1]), "bản dịch lại dài hơn bản cũ thì không được nhận"


def test_bo_siet_nllb_chi_dung_cho_trung_viet(monkeypatch, co_adapter):
    monkeypatch.setattr(translate, "_translate_nllb", lambda *a, **k: pytest.fail("không được gọi NLLB"))
    tighten = translate.make_tightener("nllb", target="vi", source="en")
    assert callable(tighten)
    tighten([{"text": "Tôi nghĩ rằng chúng ta nên đi", "target_syllables": 4, "pieces": ["Tôi nghĩ rằng chúng ta nên đi"]}])


def test_vong_lap_ngan_sach_gui_kem_cau_goc():
    class MoHinh:
        trained = True

        def predict(self, text):
            return 0.5 * len(text.split())

    cues = [Cue(0.0, 1.0, "我们获胜了。", "Chúng ta đã giành được chiến thắng rồi."), Cue(1.0, 9.0, "好。", "Tốt.")]
    seen = []

    def tightener(requests):
        seen.extend(requests)
        return ["Ta thắng rồi." for _ in requests]

    stats = budget.run_loop(cues, tightener, MoHinh())
    assert seen and seen[0]["source"] == "我们获胜了。"
    assert cues[0].text2 == "Ta thắng rồi." and stats["tightened"] == 1
