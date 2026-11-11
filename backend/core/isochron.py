"""HP-4 — token ngân sách `<len:n>` cho dịch máy đẳng thời (NLLB-200 + LoRA).

Đặt ở đây (không phụ thuộc torch) để script huấn luyện trong `training/` và engine
dịch trong `translate.py` dùng CHUNG một cách gắn token: lệch nhau một dấu cách là
mô hình đã không nhận ra token lúc chạy thật.

`<len:12>` ở đầu câu nguồn nghĩa là "dịch sao cho đọc khoảng 12 âm tiết". Lúc huấn
luyện n lấy từ chính câu đích; lúc chạy thật n lấy từ khung thời gian của câu thoại
(`budget.target_syllables`).
"""

from __future__ import annotations

from pathlib import Path

from . import duration

BUDGET_MAX = 60  # câu thoại dài hơn 60 âm tiết thì gộp vào mức cao nhất
ADAPTER_DIRNAME = "nllb_lora_dangthoi"


def budget_token(n: int) -> str:
    return f"<len:{max(1, min(BUDGET_MAX, int(n)))}>"


def all_budget_tokens() -> list[str]:
    return [budget_token(i) for i in range(1, BUDGET_MAX + 1)]


def with_budget(source_text: str, n: int | None) -> str:
    """Gắn token ngân sách vào đầu câu nguồn; n rỗng/0 thì để nguyên (dịch tự do)."""
    return f"{budget_token(n)} {source_text}" if n else source_text


def to_example(source_text: str, target_text: str, keep_budget: bool = True) -> dict:
    """Một mẫu huấn luyện: ngân sách chính là số âm tiết của câu đích."""
    n = duration.syllables(target_text)
    return {"src": with_budget(source_text, n if keep_budget else None), "tgt": target_text}


def adapter_dir(model_dir: Path) -> Path:
    return Path(model_dir) / ADAPTER_DIRNAME


def has_adapter(model_dir: Path) -> bool:
    """Thư mục adapter đã huấn luyện xong (có file cấu hình của PEFT) hay chưa."""
    return (adapter_dir(model_dir) / "adapter_config.json").is_file()
