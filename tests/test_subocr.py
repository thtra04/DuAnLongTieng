"""Kiểm thử đọc phụ đề nung sẵn trong hình (backend/core/subocr.py).

Mô hình đọc chữ không nạp trong test (cần tải ~11 MB): phần chia câu, cắt dòng, nối câu và dò dải
chạy trên khung hình tổng hợp, mô hình thay bằng bản giả. Số đo trên phim thật (22/11/2026, so với
chữ tôi đọc từ hình): 《奥德赛》 67/67 câu, Liêu Trai 251/260, The Rules EP5 (phụ đề Anh) 108/108 —
data/_bench/subocr/eval.py.
"""

from __future__ import annotations

import numpy as np

from backend.core import subocr
from backend.core.pipeline import analyze_steps

H, W = 540, 960


def _frame(rng, text_seed=None, y0=450, center=0.5, n=10, logo=False) -> np.ndarray:
    """Nền xám có vân; "phụ đề" là các nét trắng mảnh viền đen ở một dải ngang."""
    f = (np.full((H, W), 90, np.uint8) + rng.integers(0, 25, (H, W), dtype=np.uint8)).astype(np.uint8)
    if logo:                                   # logo góc trên: nét chữ đứng yên suốt phim
        _strokes(f, np.random.default_rng(99), 30, 0.5, 8)
    if text_seed is not None:
        _strokes(f, np.random.default_rng(text_seed), y0, center, n)
    return f


def _strokes(f, r, y0, center, n):
    cw, gap = 28, 6
    x0 = int(center * W - n * (cw + gap) / 2)
    for k in range(n):
        cx = x0 + k * (cw + gap)
        for _ in range(5):
            if r.random() < 0.5:
                yy, xa = y0 + int(r.integers(2, 26)), cx + int(r.integers(0, 10))
                f[yy - 3:yy + 5, xa - 3:xa + 19] = 15
                f[yy:yy + 2, xa:xa + 16] = 250
            else:
                xx, ya = cx + int(r.integers(2, 26)), y0 + int(r.integers(0, 10))
                f[ya - 3:ya + 19, xx - 3:xx + 5] = 15
                f[ya:ya + 16, xx:xx + 2] = 250


def test_do_dai_khi_nhieu_khung_khong_co_chu():
    rng = np.random.default_rng(1)
    # 40 khung rải đều: một nửa rơi vào lúc không ai nói; logo đứng yên ở trên
    frames = [_frame(rng, text_seed=(i if i % 2 == 0 or i % 5 == 0 else None), logo=True) for i in range(40)]
    band = subocr.band_from_frames(frames)
    assert band["found"], band
    assert band["y0"] < 450 / H < 478 / H < band["y1"]
    assert band["y0"] > 0.6                      # không lấy nhầm logo ở trên


def test_khong_co_phu_de_thi_khong_bao_co():
    rng = np.random.default_rng(2)
    assert not subocr.band_from_frames([_frame(rng, logo=True) for _ in range(40)])["found"]
    # chữ đứng yên (cùng một câu ở mọi khung, kiểu tên kênh) không phải phụ đề
    assert not subocr.band_from_frames([_frame(rng, text_seed=7) for _ in range(40)])["found"]


def test_cat_dong_chu_canh_giua_bo_vat_sang_o_bia():
    rng = np.random.default_rng(3)
    f = _frame(rng, text_seed=5, y0=20, n=8)[:80]            # dải cao 80 px, chữ ở giữa
    _strokes(f, np.random.default_rng(8), 20, 0.06, 1)        # một vật có nét ở sát mép trái
    lines = subocr.text_lines(subocr.stroke_mask(f), center=0.5)
    assert len(lines) == 1
    y0, y1, x0, x1 = lines[0]
    assert x0 > 0.25 * W and x1 < 0.75 * W
    assert subocr.text_lines(np.zeros((80, W), bool), 0.5) == []
    # cụm nét nằm hẳn một bên, không chứa cột giữa khung -> không phải phụ đề
    assert subocr.text_lines(subocr.stroke_mask(_frame(rng, text_seed=5, y0=20, center=0.12, n=4)[:80]), 0.5) == []


class _FakeReader:
    def __init__(self, answers):
        self.answers = list(answers)

    def read(self, images):
        return [self.answers.pop(0) for _ in images]


def _run(start, end):
    return {"start": start, "end": end, "image": np.zeros((40, 200, 3), np.uint8), "lines": [(5, 30, 10, 150)]}


def test_noi_cau_bi_cat_vun_va_bo_rac():
    runs = [_run(1.0, 1.4), _run(1.4, 2.6), _run(2.7, 2.9), _run(3.0, 4.0), _run(5.0, 5.2), _run(6.0, 7.5)]
    reader = _FakeReader([
        ("你这个老巫婆把我的士兵都变成猪", 0.90),    # cùng một câu, đọc hai lần, lần sau đủ chữ hơn
        ("你这个老巫婆把我的士兵都变成猪了", 0.97),
        ("YYSLV", 0.30),                             # nền nhiễu: độ tin thấp
        ("我要玩皇室战争", 0.99),
        ("主公", 0.99),                              # nháy 0,2 s: bỏ
        ("Then I'll take   this pair.", 0.95),
    ])
    cues, stats = subocr.to_cues(runs, reader, duration=7.0)
    assert [c.text for c in cues] == ["你这个老巫婆把我的士兵都变成猪了", "我要玩皇室战争", "Then I'll take this pair."]
    assert (cues[0].start, cues[0].end) == (1.0, 2.6)
    assert cues[-1].end == 7.0                       # không vượt độ dài phim
    assert stats["runs"] == 6 and stats["cues"] == 3


def test_ngon_ngu_theo_chu_doc_duoc():
    assert subocr.script_lang(["我是奥德修斯", "biu biu biu biu"]) == "zh"
    assert subocr.script_lang(["Do you like them, dear?", "Size 31, please."]) == "en"
    assert subocr.script_lang(["", "123"]) is None


def test_cua_so_truot_tach_duoc_khop_ban_day_du():
    rng = np.random.default_rng(4)
    a = rng.integers(0, 255, (20, 30)).astype(np.int16)
    want = np.array([[a[max(0, y - 2):y + 3, max(0, x - 2):x + 3].min() for x in range(30)] for y in range(20)])
    assert (subocr._slide(a, 2, np.minimum, None) == want).all()


def test_buoc_phan_tich_o_che_do_doc_chu_tren_hinh():
    keys = [s.key for s in analyze_steps({"source_type": "file", "sub_mode": "hardsub", "translate": True})]
    assert "ocr" in keys and "asr" not in keys and "audio" not in keys and "hardsub" not in keys
    assert keys.index("ocr") < keys.index("translate")
