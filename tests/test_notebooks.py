"""Notebook huấn luyện trong training/ phải mở được và sạch.

Notebook hỏng chỉ lộ ra khi mở Jupyter — mà đó thường là lúc đang trình bày đồ
án. Mấy test này bắt sớm: JSON hợp lệ, đúng nbformat, và không lẫn output cũ.
"""

from __future__ import annotations

import json

import pytest

from backend.config import ROOT

TRAINING = ROOT / "training"
NOTEBOOKS = sorted(TRAINING.glob("*.ipynb"))


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_co_thu_muc_training_va_notebook():
    assert TRAINING.is_dir(), "thiếu thư mục training/"
    assert NOTEBOOKS, "không có notebook nào trong training/"


def test_co_du_bon_hop_phan():
    names = {p.name for p in NOTEBOOKS}
    for phan in ("01_sinh_du_lieu_thoi_luong", "02_huan_luyen_duration",
                 "03_lora_nllb_dang_thoi", "04_khung_do_ket_qua"):
        assert any(n.startswith(phan) for n in names), f"thiếu notebook {phan}"


def test_du_lieu_mau_di_kem():
    seed = TRAINING / "data" / "seed_vi.txt"
    assert seed.is_file(), "thiếu training/data/seed_vi.txt"
    cau = [ln for ln in seed.read_text(encoding="utf-8").splitlines()
           if ln.strip() and not ln.startswith("#")]
    assert len(cau) >= 50, f"chỉ có {len(cau)} câu mẫu"


@pytest.mark.parametrize("path", NOTEBOOKS, ids=lambda p: p.name)
def test_mo_duoc_va_dung_dinh_dang(path):
    nb = load(path)
    assert nb.get("nbformat") == 4, "Jupyter đời mới đọc nbformat 4"
    assert nb.get("cells"), "notebook rỗng"
    for i, cell in enumerate(nb["cells"]):
        assert cell["cell_type"] in ("code", "markdown"), f"ô {i} lạ kiểu"
        assert isinstance(cell["source"], list), f"ô {i}: source phải là list dòng"


@pytest.mark.parametrize("path", NOTEBOOKS, ids=lambda p: p.name)
def test_co_giai_thich_khong_chi_toan_code(path):
    """Người chấm đọc notebook chứ không chỉ chạy — phải có phần chữ."""
    nb = load(path)
    kinds = [c["cell_type"] for c in nb["cells"]]
    assert "markdown" in kinds, "không có ô giải thích nào"
    assert "code" in kinds, "không có ô code nào"


@pytest.mark.parametrize("path", NOTEBOOKS, ids=lambda p: p.name)
def test_khong_luu_output_cu(path):
    """Output cũ làm diff phình to và có thể lộ đường dẫn máy cá nhân."""
    nb = load(path)
    ban = [
        i for i, c in enumerate(nb["cells"])
        if c["cell_type"] == "code" and (c.get("outputs") or c.get("execution_count") is not None)
    ]
    assert not ban, f"ô còn output/số thứ tự chạy: {ban} — Restart & Clear Output rồi commit lại"


@pytest.mark.parametrize("path", NOTEBOOKS, ids=lambda p: p.name)
def test_tu_tim_goc_du_an(path):
    """Mở notebook từ thư mục nào cũng phải import được backend."""
    nb = load(path)
    dau = "".join("".join(c["source"]) for c in nb["cells"] if c["cell_type"] == "code")
    assert "sys.path.insert" in dau, "thiếu đoạn thêm gốc dự án vào sys.path"
