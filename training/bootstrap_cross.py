"""Khoảng tin cậy 95 % (bootstrap ghép cặp) cho bảng chéo của eval_nllb_lora.py.

    python training/bootstrap_cross.py                       # đọc data/_bench/nllb_lora_cross/<tập>.json
    python training/bootstrap_cross.py --n 2000 --out data/_bench/nllb_lora_cross_ci.json

Mỗi tập kiểm tra: so từng cấu hình (adapter + `<len:n>`, adapter không token) với NLLB gốc trên
CÙNG các câu — lấy mẫu lại câu có hoàn lại, tính lại chênh lệch. Chênh lệch "có ý nghĩa" khi
khoảng 95 % không chứa 0. Chỉ số: ±1 âm tiết (%), phải nén (dài hơn n quá budget.TOLERANCE, %),
chrF và BLEU mức corpus.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.core import budget, duration  # noqa: E402

norm = lambda s: unicodedata.normalize("NFC", s or "").strip()  # noqa: E731


def per_sentence(hyp: list[str], ref: list[str]) -> tuple[list[int], list[int]]:
    within, over = [], []
    for h, r in zip(hyp, ref):
        g, t = duration.syllables(norm(h)), duration.syllables(norm(r))
        within.append(int(abs(g - t) <= 1))
        over.append(int(g > t * (1 + budget.TOLERANCE)))
    return within, over


def ci(values: list[float]) -> tuple[float, float]:
    v = sorted(values)
    return v[int(0.025 * len(v))], v[int(0.975 * len(v)) - 1]


def main() -> None:
    import sacrebleu

    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dir", type=Path, default=ROOT / "data" / "_bench" / "nllb_lora_cross")
    ap.add_argument("--n", type=int, default=1000, help="số lượt lấy mẫu lại")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", type=Path, default=ROOT / "data" / "_bench" / "nllb_lora_cross_ci.json")
    args = ap.parse_args()

    chrf, bleu = sacrebleu.CHRF(), sacrebleu.BLEU()
    out = []
    for path in sorted(args.dir.glob("*.json")):
        lang = path.stem
        rows = json.loads(path.read_text(encoding="utf-8"))
        ref = [norm(r["ref"]) for r in rows]
        runs = [k for k in rows[0] if k not in ("src", "ref")]
        hyp = {k: [norm(r[k]) for r in rows] for k in runs}
        stats = {k: per_sentence(hyp[k], ref) for k in runs}
        # thống kê n-gram từng câu (đúng cách sacrebleu tự làm bootstrap) để tính lại điểm corpus trên mẫu lại
        cs = {k: chrf._extract_corpus_statistics(hyp[k], [ref]) for k in runs}
        bs = {k: bleu._extract_corpus_statistics(hyp[k], [ref]) for k in runs}

        def corpus(metric, sent_stats, idx):
            return metric._aggregate_and_compute([sent_stats[i] for i in idx]).score

        rng = random.Random(args.seed)
        n = len(rows)
        samples = [[rng.randrange(n) for _ in range(n)] for _ in range(args.n)]
        base = "goc"
        for k in runs:
            if k == base:
                continue
            res = {"lang": lang, "run": k, "vs": base, "n": n}
            for name, (a, b) in (("within_1_pct", (stats[k][0], stats[base][0])),
                                 ("over_tol_pct", (stats[k][1], stats[base][1]))):
                d = [100 * sum(a[i] - b[i] for i in idx) / n for idx in samples]
                res[name] = {"diff": round(100 * (sum(a) - sum(b)) / n, 1), "ci95": [round(x, 1) for x in ci(d)]}
            all_idx = range(n)
            for name, metric, st in (("chrf", chrf, cs), ("bleu", bleu, bs)):
                d0 = corpus(metric, st[k], all_idx) - corpus(metric, st[base], all_idx)
                d = [corpus(metric, st[k], idx) - corpus(metric, st[base], idx) for idx in samples]
                res[name] = {"diff": round(d0, 2), "ci95": [round(x, 2) for x in ci(d)]}
            out.append(res)
            sig = lambda m: "*" if not (res[m]["ci95"][0] <= 0 <= res[m]["ci95"][1]) else " "  # noqa: E731
            print(f"{lang} {k:7s} ±1 {res['within_1_pct']['diff']:+6.1f} {res['within_1_pct']['ci95']}{sig('within_1_pct')} "
                  f"phải nén {res['over_tol_pct']['diff']:+6.1f} {res['over_tol_pct']['ci95']}{sig('over_tol_pct')} "
                  f"chrF {res['chrf']['diff']:+5.2f} {res['chrf']['ci95']}{sig('chrf')} "
                  f"BLEU {res['bleu']['diff']:+5.2f} {res['bleu']['ci95']}{sig('bleu')}", flush=True)
    args.out.write_text(json.dumps({"n_resamples": args.n, "rows": out}, ensure_ascii=False, indent=1), encoding="utf-8")
    print("Đã ghi", args.out, "— * = khoảng 95 % không chứa 0")


if __name__ == "__main__":
    main()
