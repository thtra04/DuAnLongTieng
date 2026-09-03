"""Kiểm thử HP-3 — mô hình dự đoán thời lượng đọc tiếng Việt."""

from __future__ import annotations

import random

import pytest

from app import duration
from app.duration import (
    FEATURE_NAMES,
    DurationModel,
    default_model,
    evaluate,
    features,
    heuristic_seconds,
    reset_default,
    syllables,
)


# ------------------------------------------------------------ đặc trưng


@pytest.mark.parametrize(
    "text,n",
    [
        ("Xin chào các bạn", 4),
        ("Tôi đi học.", 3),
        ("Một, hai — ba!", 3),
        ("", 0),
        ("   ", 0),
        ("你好世界", 4),
        # chữ số được đọc thành tiếng ("ba"), nên phải tính là một âm tiết
        ("Anh ấy có 3 con mèo", 6),
    ],
)
def test_dem_am_tiet(text, n):
    assert syllables(text) == n


def test_vector_dac_trung_dung_do_dai_va_he_so_chan():
    x = features("Xin chào, bạn khoẻ không?")
    assert len(x) == len(FEATURE_NAMES)
    assert x[0] == 1.0
    assert x[1] == 5.0  # âm tiết
    assert x[3] == 1.0  # dấu phẩy
    assert x[5] == 1.0  # dấu hỏi


def test_uoc_luong_tho_tang_theo_do_dai():
    assert heuristic_seconds("") == 0.0
    assert heuristic_seconds("Dạ.") < heuristic_seconds("Dạ, em xin phép được trình bày.")


# ------------------------------------------------------------ huấn luyện


def du_lieu_gia(n=120, seed=1):
    """Câu tiếng Việt giả với thời lượng tuyến tính theo âm tiết + nhiễu nhỏ."""
    rng = random.Random(seed)
    tu = ["tôi", "đi", "học", "hôm", "nay", "trời", "rất", "đẹp", "và", "mát", "mẻ", "quá", "chừng"]
    texts, secs = [], []
    for _ in range(n):
        k = rng.randint(1, 20)
        s = " ".join(rng.choice(tu) for _ in range(k)) + rng.choice([".", "?", "!", ","])
        texts.append(s)
        secs.append(0.23 * k + 0.35 + rng.uniform(-0.03, 0.03))
    return texts, secs


def test_hoc_duoc_quan_he_tuyen_tinh():
    texts, secs = du_lieu_gia()
    model = DurationModel.fit(texts, secs)
    assert model.trained
    assert model.mae(texts, secs) < 0.05, "dữ liệu tuyến tính thì hồi quy tuyến tính phải khớp sát"
    assert model.meta["n"] == len(texts) and "train_mae" in model.meta


def test_du_doan_tot_hon_uoc_luong_tho():
    texts, secs = du_lieu_gia(seed=7)
    model = DurationModel.fit(texts[:100], secs[:100])
    rep = evaluate(model, texts[100:], secs[100:])
    assert rep["n"] == 20
    assert rep["mae_ms"] < rep["heuristic_mae_ms"]
    assert rep["improvement"] > 0


def test_du_doan_cau_rong_bang_khong_va_co_san_toi_thieu():
    texts, secs = du_lieu_gia()
    model = DurationModel.fit(texts, secs)
    assert model.predict("") == 0.0
    assert model.predict("Ừ") >= 0.15


def test_chua_huan_luyen_thi_roi_ve_uoc_luong_tho():
    m = DurationModel()
    assert not m.trained
    assert m.predict("Xin chào các bạn") == pytest.approx(heuristic_seconds("Xin chào các bạn"))


def test_du_lieu_lech_bi_tu_choi():
    with pytest.raises(ValueError):
        DurationModel.fit(["a", "b"], [1.0])
    with pytest.raises(ValueError):
        DurationModel.fit([], [])


# ------------------------------------------------------------- lưu / nạp


def test_luu_roi_nap_lai_du_doan_y_het(workdir):
    texts, secs = du_lieu_gia()
    model = DurationModel.fit(texts, secs)
    path = model.save(workdir / "m.json")
    lai = DurationModel.load(path)
    for t in texts[:5]:
        assert lai.predict(t) == pytest.approx(model.predict(t))


def test_nap_mo_hinh_khac_bo_dac_trung_bi_tu_choi(workdir):
    p = workdir / "cu.json"
    p.write_text('{"weights": [1, 2], "features": ["bias", "chars"]}', encoding="utf-8")
    with pytest.raises(ValueError):
        DurationModel.load(p)


def test_mo_hinh_mac_dinh_khi_chua_co_file(workdir, monkeypatch):
    monkeypatch.setattr(duration, "MODEL_PATH", workdir / "khong-co.json")
    reset_default()
    assert not default_model().trained


def test_mo_hinh_mac_dinh_nap_tu_dia(workdir, monkeypatch):
    texts, secs = du_lieu_gia()
    path = workdir / "duration_vi.json"
    DurationModel.fit(texts, secs).save(path)
    monkeypatch.setattr(duration, "MODEL_PATH", path)
    reset_default()
    assert default_model().trained
    reset_default()


def test_danh_gia_tap_rong():
    rep = evaluate(DurationModel(), [], [])
    assert rep["n"] == 0 and rep["mae_ms"] is None
