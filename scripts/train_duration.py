"""Huấn luyện mô hình dự đoán thời lượng đọc (HP-3) từ CSV do gen_duration_data.py sinh.

    uv run python scripts/train_duration.py --data data/duration/samples.csv

Tách 10% cuối làm tập kiểm tra (theo thứ tự cố định sau khi xáo với seed), in
MAE của mô hình và của ước lượng thô, rồi lưu mô hình vào data/models/duration_vi.json
— nơi `app.duration.default_model()` sẽ tự nạp.
"""

from __future__ import annotations

import argparse
import csv
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.core import duration  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=ROOT / "data" / "duration" / "samples.csv", type=Path)
    ap.add_argument("--output", default=duration.MODEL_PATH, type=Path)
    ap.add_argument("--test-ratio", type=float, default=0.1)
    ap.add_argument("--ridge", type=float, default=1e-2)
    ap.add_argument("--seed", type=int, default=13)
    args = ap.parse_args()

    with args.data.open(encoding="utf-8", newline="") as fh:
        rows = [(r["text"], float(r["seconds"])) for r in csv.DictReader(fh) if r.get("text")]
    if len(rows) < 10:
        print(f"Chỉ có {len(rows)} mẫu — cần ít nhất 10 để chia tập kiểm tra.")
        return 1

    random.Random(args.seed).shuffle(rows)
    n_test = max(1, int(len(rows) * args.test_ratio))
    test, train = rows[:n_test], rows[n_test:]

    model = duration.DurationModel.fit([t for t, _ in train], [s for _, s in train], ridge=args.ridge)
    rep = duration.evaluate(model, [t for t, _ in test], [s for _, s in test])
    print(f"Huấn luyện {len(train)} câu, kiểm tra {len(test)} câu")
    print(f"  MAE mô hình     : {rep['mae_ms']:.0f} ms  (RMSE {rep['rmse_ms']:.0f} ms)")
    print(f"  MAE ước lượng thô: {rep['heuristic_mae_ms']:.0f} ms")
    print(f"  Cải thiện        : {rep['improvement'] * 100:.1f}%")
    if len(test) < 100:
        print(
            f"  Tập kiểm tra chỉ có {len(test)} câu — số đo này chưa nói lên gì về MT-3. "
            "Cần dữ liệu thật (đề cương: 30.000–50.000 câu) rồi mới kết luận."
        )
    else:
        print("  Mục tiêu đề cương (MT-3): MAE < 200 ms ->", "ĐẠT" if rep["mae_ms"] < 200 else "chưa đạt")

    model.meta.update({"test": rep, "data": str(args.data)})
    path = model.save(args.output)
    print("Đã lưu ->", path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
