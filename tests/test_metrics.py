"""Kiểm thử khung đo tự động — Bảng 5.2 của đề cương."""

from __future__ import annotations

import json

import pytest

from backend.core import metrics
from backend.core.metrics import (
    CONFIGS,
    aggregate,
    bleu,
    build_record,
    collect,
    config_of,
    export_for_labeling,
    import_labels,
    isochrony_metrics,
    realtime_factor,
    speaker_accuracy,
    to_csv,
    to_markdown,
    write_record,
)
from backend.core.subtitles import Cue


def c(i, speaker=""):
    return Cue(start=float(i), end=float(i) + 1, text=f"câu {i}", speaker=speaker)


# ------------------------------------------------------------ cấu hình


def test_nam_cau_hinh_dung_thu_tu_de_cuong():
    assert list(CONFIGS) == ["C0", "C1", "C2", "C3", "C4"]


def test_suy_cau_hinh_tu_cong_tac():
    assert config_of({}) == "C0"
    assert config_of({"engine": "claude"}) == "C1"
    assert config_of({"diarize": True}) == "C2"
    assert config_of({"diarize": True, "isochronic": True}) == "C3"
    assert config_of({"diarize": True, "isochronic": True, "budget_loop": True}) == "C4"


def test_ghi_de_cau_hinh_bang_tay():
    assert config_of({"eval_config": "c2"}) == "C2"
    assert config_of({"eval_config": "C9", "diarize": True}) == "C2", "mã lạ thì suy như thường"


# ------------------------------------------------------------ đẳng thời


def test_ba_chi_so_dang_thoi():
    stats = {"count": 69, "sped_up": 48, "max_factor": 1.48, "overflow": 2, "overflow_s": 3.4}
    m = isochrony_metrics(stats)
    assert m["compress_ratio"] == pytest.approx(48 / 69, abs=1e-4)
    assert m["max_factor"] == 1.48
    assert m["overflow_count"] == 2 and m["overflow_s"] == 3.4


def test_khong_doc_duoc_cau_nao_thi_ti_le_bang_khong():
    m = isochrony_metrics({"count": 0, "sped_up": 0})
    assert m["compress_ratio"] == 0.0 and m["max_factor"] == 1.0


def test_he_so_thoi_gian_thuc():
    assert realtime_factor(60, 120) == 0.5
    assert realtime_factor(60, 0) is None
    assert realtime_factor(None, 120) is None


# --------------------------------------------------------- gán nhãn tay


def test_xuat_bang_gan_nhan_de_trong_cot_gold():
    rows = export_for_labeling([c(0, "S1"), c(1, "S2")])
    assert [r["predicted"] for r in rows] == ["S1", "S2"]
    assert all(r["gold"] == "" for r in rows), "không được điền sẵn nhãn máy vào cột người gán"


def test_doc_lai_nhan_bo_qua_dong_trong_va_hong():
    gold = import_labels([
        {"index": 0, "gold": "Hoàng đế"},
        {"index": 1, "gold": ""},
        {"index": "x", "gold": "A"},
        {"index": 2, "gold": "  Thần  "},
    ])
    assert gold == {0: "Hoàng đế", 2: "Thần"}


def test_gan_dung_het_du_dat_ten_khac():
    """Máy gọi S1/S2, người gọi A/B — phải tìm ánh xạ chứ không chấm 0."""
    cues = [c(0, "S1"), c(1, "S2"), c(2, "S1"), c(3, "S2")]
    r = speaker_accuracy(cues, {0: "A", 1: "B", 2: "A", 3: "B"})
    assert r["accuracy"] == 1.0
    assert r["mapping"] == {"S1": "A", "S2": "B"}


def test_gan_sai_mot_phan():
    cues = [c(0, "S1"), c(1, "S1"), c(2, "S1"), c(3, "S2")]
    r = speaker_accuracy(cues, {0: "A", 1: "A", 2: "B", 3: "B"})
    assert r["n"] == 4 and r["correct"] == 3
    assert r["accuracy"] == 0.75


def test_cue_may_de_trong_tinh_la_sai():
    cues = [c(0, "S1"), c(1, "")]
    r = speaker_accuracy(cues, {0: "A", 1: "A"})
    assert r["correct"] == 1


def test_khong_co_nhan_nguoi_thi_khong_cham():
    assert speaker_accuracy([c(0, "S1")], {})["accuracy"] is None


def test_chi_cham_cue_co_nhan_nguoi():
    cues = [c(0, "S1"), c(1, "S2"), c(2, "S9")]
    r = speaker_accuracy(cues, {0: "A", 1: "B"})
    assert r["n"] == 2 and r["accuracy"] == 1.0


def test_may_tach_qua_nhieu_nhan_vat_bi_tru_diem():
    """Máy chia một người thành hai — chỉ một nhãn máy được ghép với người đó."""
    cues = [c(0, "S1"), c(1, "S2"), c(2, "S1"), c(3, "S2")]
    r = speaker_accuracy(cues, {0: "A", 1: "A", 2: "A", 3: "A"})
    assert r["correct"] == 2 and r["accuracy"] == 0.5


def test_nhieu_nhan_vat_dung_duong_tham_lam():
    cues = [c(i, f"S{i % 10 + 1}") for i in range(30)]
    gold = {i: f"P{i % 10}" for i in range(30)}
    r = speaker_accuracy(cues, gold)
    assert r["accuracy"] == 1.0 and r["pred_speakers"] == 10


def test_chi_so_cue_ngoai_pham_vi_bi_bo_qua():
    r = speaker_accuracy([c(0, "S1")], {0: "A", 99: "B"})
    assert r["n"] == 1


# ----------------------------------------------------------- BLEU


def test_bleu_tuy_chon():
    out = bleu(["xin chào"], ["xin chào"])
    assert out is None or isinstance(out, float)


def test_bleu_dau_vao_lech_tra_none():
    assert bleu(["a"], ["a", "b"]) is None
    assert bleu([], []) is None


# ---------------------------------------------------------- bản ghi


def test_ban_ghi_du_truong(workdir):
    rec = build_record(
        job_id="j1", cfg={"diarize": True, "engine": "google", "source_lang": "zh"},
        dub_stats={"count": 10, "sped_up": 2, "max_factor": 1.2, "overflow": 0, "overflow_s": 0},
        duration_s=100, elapsed_s=50, speaker={"accuracy": 0.9, "n": 20},
    )
    assert rec["config"] == "C2"
    assert rec["compress_ratio"] == 0.2 and rec["rtf"] == 0.5
    assert rec["speaker_accuracy"] == 0.9 and rec["source_lang"] == "zh"

    path = write_record(workdir / "jobs" / "j1" / "eval.json", rec)
    assert json.loads(path.read_text(encoding="utf-8"))["job"] == "j1"


def test_gom_ban_ghi_bo_qua_file_hong(workdir):
    jobs = workdir / "jobs"
    write_record(jobs / "a" / "eval.json", {"job": "a", "config": "C0"})
    write_record(jobs / "b" / "eval.json", {"job": "b", "config": "C4"})
    (jobs / "c").mkdir()
    (jobs / "c" / "eval.json").write_text("{ hỏng", encoding="utf-8")

    assert sorted(r["job"] for r in collect(jobs)) == ["a", "b"]
    assert collect(workdir / "khong-co") == []


def test_gom_theo_cau_hinh_tinh_trung_binh():
    rows = aggregate([
        {"config": "C4", "compress_ratio": 0.1, "max_factor": 1.1},
        {"config": "C0", "compress_ratio": 0.7, "max_factor": 1.5},
        {"config": "C0", "compress_ratio": 0.5, "max_factor": 1.3},
        {"config": "X9", "compress_ratio": 0.2},
    ])
    assert [r["config"] for r in rows] == ["C0", "C4", "X9"], "đường cơ sở đứng đầu, cấu hình lạ cuối"
    c0 = rows[0]
    assert c0["runs"] == 2 and c0["compress_ratio"] == 0.6 and c0["max_factor"] == 1.4
    assert c0["bleu"] is None


def test_bang_markdown_va_csv():
    rows = aggregate([{"config": "C0", "compress_ratio": 0.696, "max_factor": 1.48, "overflow_s": 2.0}])
    md = to_markdown(rows)
    assert md.splitlines()[0].startswith("| Cấu hình |")
    assert "| C0 |" in md and "0.696" in md and "—" in md, "thiếu số thì hiện gạch, không hiện None"
    csv_text = to_csv(rows)
    assert csv_text.splitlines()[0].startswith("Cấu hình,")
    assert "C0,1,0.696" in csv_text
