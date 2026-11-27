"""HP-4 — token ngân sách `<len:n>` cho dịch máy đẳng thời (NLLB-200 + LoRA).

Đặt ở đây (không phụ thuộc torch) để script huấn luyện trong `training/` và engine
dịch trong `translate.py` dùng CHUNG một cách gắn token: lệch nhau một dấu cách là
mô hình đã không nhận ra token lúc chạy thật.

`<len:12>` ở đầu câu nguồn nghĩa là "dịch sao cho đọc khoảng 12 âm tiết". Lúc huấn
luyện n lấy từ chính câu đích; lúc chạy thật n lấy từ khung thời gian của câu thoại
(`budget.target_syllables`).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from . import duration

BUDGET_MAX = 60  # câu thoại dài hơn 60 âm tiết thì gộp vào mức cao nhất
ADAPTER_DIRNAME = "nllb_lora_dangthoi"
# Ngôn ngữ nguồn có adapter riêng (đích luôn là tiếng Việt). Trung → Việt nằm ở thư mục gốc
# `nllb_lora_dangthoi` (huấn luyện 11/11/2026); các thứ tiếng sau thêm hậu tố `_ko`, `_ja`, `_en`.
LANGS = ("zh", "ko", "ja", "en")
NLLB_SRC = {"zh": "zho_Hans", "ko": "kor_Hang", "ja": "jpn_Jpan", "en": "eng_Latn"}


def dialogue_adapters() -> dict[str, Path]:
    """Only load completed candidates explicitly selected by the studio host."""
    selected = {}
    for task in ("meaning", "spoken"):
        directory = os.environ.get(f"VSUB_{task.upper()}_ADAPTER")
        if not directory:
            continue
        path = Path(directory)
        try:
            meta = json.loads((path / "train_meta.json").read_text(encoding="utf-8"))
            src = meta["src_lang"]
            if (meta["finished"] is True and meta["task"] == task
                    and meta["base_model"] == "facebook/nllb-200-distilled-600M"
                    and src in (LANGS if task == "meaning" else ("vi",))
                    and (path / "adapter_model.safetensors").is_file() and (path / "adapter_config.json").is_file()):
                selected[f"{task}_{src}"] = path
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return selected


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


def adapter_dir(model_dir: Path, lang: str = "zh") -> Path:
    return Path(model_dir) / (ADAPTER_DIRNAME if lang == "zh" else f"{ADAPTER_DIRNAME}_{lang}")


def has_adapter(model_dir: Path, lang: str = "zh") -> bool:
    """Thư mục adapter đã huấn luyện xong (có file cấu hình của PEFT) hay chưa."""
    return (adapter_dir(model_dir, lang) / "adapter_config.json").is_file()


def adapter_langs(model_dir: Path) -> list[str]:
    """Các ngôn ngữ nguồn đã có adapter, theo thứ tự LANGS."""
    return [lang for lang in LANGS if has_adapter(model_dir, lang)]


def lang_key(nllb_src: str) -> str | None:
    """Mã NLLB của câu nguồn → khoá adapter ('zh', 'ko'…), hoặc None nếu không có loại adapter đó."""
    return next((k for k, v in NLLB_SRC.items() if v == nllb_src), None)
