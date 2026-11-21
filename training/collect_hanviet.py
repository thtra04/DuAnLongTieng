"""Gom cụm Hán Việt từ các dự án Trung → Việt đã làm vào bộ thuật ngữ tự học (data/hanviet_learned.json).

    .venv/Scripts/python training/collect_hanviet.py            # ghi
    .venv/Scripts/python training/collect_hanviet.py --dry-run  # chỉ in ra

Từ lúc có `backend/core/hanviet.py`, app tự học khi dịch (bộ thuật ngữ đang dùng, tên riêng
trong bản AI) và khi xuất (chỗ người dùng sửa tay). Script này học bù từ những dự án làm
TRƯỚC đó, theo đúng các luật ấy:

* bộ thuật ngữ người dùng đã gõ ở từng dự án (`cfg.glossary`)  → nguồn "thuật ngữ";
* dự án dịch bằng Claude / OpenAI: tên riêng viết hoa gặp từ hai câu trở lên → nguồn "AI".

Bản tham chiếu của bộ gold (data/_bench/gold) KHÔNG được dùng: đó là tập kiểm thử.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.core import hanviet, translate  # noqa: E402


def main() -> None:
    from backend.config import DATA_DIR

    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    gloss: list[tuple[str, str]] = []
    ai_pairs: list[tuple[str, str]] = []
    projects = 0
    for state in sorted(Path(DATA_DIR, "jobs").glob("*/state.json")):
        try:
            s = json.loads(state.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        cfg = s.get("cfg") or {}
        if not hanviet.enabled(s.get("source_lang") or cfg.get("source_lang"), s.get("target_lang") or "vi"):
            continue
        projects += 1
        gloss += [p for p in translate.parse_glossary(cfg.get("glossary") or "") if hanviet.is_han(p[0])]
        if (cfg.get("engine") or "") in ("claude", "openai"):
            ai_pairs += [(c.get("text") or "", c.get("text2") or "") for c in s.get("cues") or []]

    names = hanviet.harvest_many(ai_pairs)
    ai = sorted({p for p, n in names.items() if n >= 2 and p[1][:1].isupper()})
    print(f"{projects} dự án Trung → Việt: {len(set(gloss))} mục thuật ngữ, {len(ai)} tên riêng từ bản dịch AI")
    for z, v in sorted(set(gloss)):
        print(f"  thuật ngữ  {z} → {v}")
    for z, v in ai:
        print(f"  AI         {z} → {v}")
    if not args.dry_run:
        changed = hanviet.learn(sorted(set(gloss)), "thuật ngữ") + hanviet.learn(ai, "AI")
        print(f"Đã ghi {changed} cụm mới vào {hanviet._path()} (tổng {len(hanviet.load())})")


if __name__ == "__main__":
    main()
