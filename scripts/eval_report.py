"""Gom mọi bản ghi đo đạc (data/jobs/*/eval.json) thành bảng so sánh C0…C4.

    uv run python scripts/eval_report.py                 # in bảng Markdown
    uv run python scripts/eval_report.py --csv ket-qua.csv
    uv run python scripts/eval_report.py --raw           # in từng lần chạy

Đây là Bảng 5.2 của đề cương sinh ra từ dữ liệu thật — dán thẳng vào báo cáo.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.core import metrics  # noqa: E402
from backend.config import JOB_DIR  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--jobs", default=JOB_DIR, type=Path, help="thư mục chứa các job")
    ap.add_argument("--csv", type=Path, help="ghi thêm ra CSV")
    ap.add_argument("--raw", action="store_true", help="in từng bản ghi thay vì gom")
    args = ap.parse_args()

    records = metrics.collect(args.jobs)
    if not records:
        print(f"Chưa có bản ghi nào trong {args.jobs} — chạy lồng tiếng ít nhất một lần đã.")
        return 1

    if args.raw:
        for r in records:
            print(json.dumps(r, ensure_ascii=False))
        return 0

    rows = metrics.aggregate(records)
    print(f"{len(records)} lần chạy, {len(rows)} cấu hình\n")
    print(metrics.to_markdown(rows))
    print()
    for row in rows:
        note = metrics.CONFIGS.get(row["config"], {}).get("label", "")
        if note:
            print(f"  {row['config']}: {note}")
    if args.csv:
        args.csv.write_text(metrics.to_csv(rows), encoding="utf-8")
        print("\nĐã ghi ->", args.csv)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
