"""HP-4 — đo NLLB gốc so với NLLB + LoRA đẳng thời trên bộ gold và trên tập dev.

    python training/eval_nllb_lora.py            # in bảng, ghi data/_bench/gold/nllb_*_vi.json
    python data/_bench/score_vi.py data/_bench/gold/nllb_*_vi.json   # bảng BLEU/chrF chung

Các cột trên bộ gold (271 câu thoại cổ trang, dịch TỪNG DÒNG bằng chính
`translate._translate_nllb` của app):

    nllb_goc        NLLB-200 distilled 600M nguyên bản
    nllb_goc_luat   … rồi rút gọn bằng luật tiếng Việt (HP-5, `shorten.py`)
    nllb_lora       NLLB + LoRA, không gắn token ngân sách
    nllb_lora_len   … rồi câu nào vượt khung thì dịch lại từng dòng với token `<len:n>`
    nllb_lora_app   … như trên nhưng bằng bộ siết của app (`translate.make_tightener`)

Tỉ lệ vượt khung đo bằng chính `budget.assess` / `budget.over_budget` của app (theo
đơn vị đọc TTS), kèm một số đo theo từng dòng để nhìn rõ hơn (68 đơn vị là ít).

Tập dev (cặp OpenSubtitles tách riêng lúc huấn luyện) trả lời câu hỏi "token có
điều khiển được độ dài không": cho n = số âm tiết của bản tham chiếu rồi đo độ lệch.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from backend.core import budget, duration, isochron, shorten, translate  # noqa: E402
from backend.core.subtitles import Cue  # noqa: E402
from backend.core.translate import _join_fragments  # noqa: E402

import train_nllb_lora as T  # noqa: E402

GOLD = ROOT / "data" / "_bench" / "gold"
norm = lambda s: unicodedata.normalize("NFC", s or "").strip()  # noqa: E731


class Translator:
    """Gọi đúng đường mã của app (`translate._translate_nllb`), bật/tắt adapter bằng VSUB_NLLB_LORA."""

    def __init__(self, lora: bool):
        os.environ["VSUB_NLLB_LORA"] = "1" if lora else "0"
        translate._nllb_cache.clear()
        self.lora = translate._load_nllb()[3]
        if lora and not self.lora:
            raise RuntimeError("Không nạp được adapter LoRA (thiếu peft hoặc adapter hỏng).")

    def __call__(self, texts: list[str], budgets: list[int | None] | None = None) -> list[str]:
        return translate._translate_nllb(texts, "zh", "vi", budgets=budgets)

    def close(self) -> None:
        translate._nllb_cache.clear()


def token_tightener(cues: list[Cue], tr: Translator):
    """Bộ siết HP-4: dịch lại từng dòng của đơn vị vượt khung với token ngân sách nhỏ hơn."""

    def tighten(requests: list[dict]) -> list:
        jobs = []
        for r in requests:
            scale = r["target_syllables"] / max(1, r["syllables"])
            for i, piece in zip(r["cues"], r["pieces"]):
                jobs.append((cues[i].text, max(1, int(duration.syllables(piece) * scale))))
        new = iter(tr([j[0] for j in jobs], [j[1] for j in jobs]))
        out = []
        for r in requests:
            pieces = [next(new) for _ in r["cues"]]
            # chỉ nhận mảnh nào thật sự ngắn đi; không thì giữ bản cũ
            out.append([p if p and duration.syllables(p) < duration.syllables(old) else old
                        for p, old in zip(pieces, r["pieces"])])
        return out

    return tighten


def line_over(cues: list[Cue], model) -> int:
    """Số DÒNG mà bản dịch riêng dòng đó đọc không kịp khung của chính nó."""
    n = 0
    for i, c in enumerate(cues):
        win = budget.window_seconds(cues, [i])
        if c.text2.strip() and win > 0 and model.predict(c.text2) / win > 1 + budget.TOLERANCE:
            n += 1
    return n


def measure(name: str, cues: list[Cue], gold: list[dict], ref: dict[int, str], model) -> dict:
    import sacrebleu

    rows = [{"idx": g["idx"], "start": g["start"], "end": g["end"], "zh": g["text"], "vi": c.text2}
            for g, c in zip(gold, cues)]
    (GOLD / f"{name}_vi.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    hyp = [norm(r["vi"]) for r in rows]
    refs = [norm(ref[r["idx"]]) for r in rows]
    items = budget.assess(cues, model)
    over = budget.over_budget(items)
    return {
        "name": name,
        "bleu": round(sacrebleu.corpus_bleu(hyp, [refs]).score, 1),
        "chrf": round(sacrebleu.corpus_chrf(hyp, [refs]).score, 1),
        "units": len(items), "over_units": len(over),
        "over_units_pct": round(100 * len(over) / max(1, len(items)), 1),
        "lines": len(cues), "over_lines": line_over(cues, model),
        "syllables": sum(duration.syllables(h) for h in hyp),
        "ref_syllables": sum(duration.syllables(r) for r in refs),
    }


def eval_gold(base: Translator | None, lora: Translator | None) -> list[dict]:
    gold = json.loads((GOLD / "gold.json").read_text(encoding="utf-8"))
    ref = {int(ln.split("\t")[0]): ln.split("\t", 1)[1].strip()
           for ln in (GOLD / "ref_vi.tsv").read_text(encoding="utf-8").splitlines() if ln.strip()}
    model = duration.default_model()
    texts = [g["text"] for g in gold]
    fresh = lambda vi: [Cue(g["start"], g["end"], g["text"], v) for g, v in zip(gold, vi)]  # noqa: E731
    out = []
    if base:
        cues = fresh(base(texts))
        out.append(measure("nllb_goc", cues, gold, ref, model))
        cues = copy.deepcopy(cues)
        budget.run_loop(cues, shorten.make_tightener(), model)
        out.append(measure("nllb_goc_luat", cues, gold, ref, model))
    if lora:
        cues = fresh(lora(texts))
        out.append(measure("nllb_lora", cues, gold, ref, model))
        cues = copy.deepcopy(cues)
        stats = budget.run_loop(cues, token_tightener(cues, lora), model, on_log=print)
        row = measure("nllb_lora_len", cues, gold, ref, model)
        row["loop"] = {k: stats[k] for k in ("over_before", "over_after", "passes", "tightened")}
        out.append(row)
        # đúng bộ siết app dùng: dịch lại CẢ đơn vị đọc với token rồi chia lại vào từng dòng
        cues = fresh([r["vi"] for r in json.loads((GOLD / "nllb_lora_vi.json").read_text(encoding="utf-8"))])
        budget.run_loop(cues, translate.make_tightener("nllb", target="vi", source="zh"), model)
        out.append(measure("nllb_lora_app", cues, gold, ref, model))
    return out


def eval_dev(base: Translator | None, lora: Translator | None, corpus: Path, n_dev: int, seed: int) -> list[dict]:
    """Trên cặp dev (không tham gia huấn luyện): chất lượng và độ bám ngân sách."""
    import sacrebleu

    pairs = T.load_pairs(corpus, {"extra"}, 0, seed)[:n_dev]
    src, ref = [p["src"] for p in pairs], [norm(p["tgt"]) for p in pairs]
    want = [duration.syllables(r) for r in ref]
    runs = []
    if base:
        runs.append(("nllb_goc", base(src), want))
    if lora:
        runs.append(("nllb_lora (không token)", lora(src), want))
        runs.append(("nllb_lora <len:n>, n = tham chiếu", lora(src, want), want))
        short = [max(1, round(w * 0.7)) for w in want]
        runs.append(("nllb_lora <len:n>, n = 0,7 × tham chiếu", lora(src, short), short))
    out = []
    for name, hyp, target in runs:
        got = [duration.syllables(h) for h in hyp]
        diff = [abs(g - t) for g, t in zip(got, target)]
        out.append({
            "name": name,
            "bleu": round(sacrebleu.corpus_bleu([norm(h) for h in hyp], [ref]).score, 1),
            "chrf": round(sacrebleu.corpus_chrf([norm(h) for h in hyp], [ref]).score, 1),
            "mae_syllables": round(sum(diff) / len(diff), 2),
            "within_1_pct": round(100 * sum(d <= 1 for d in diff) / len(diff), 1),
            "over_target_pct": round(100 * sum(g > t for g, t in zip(got, target)) / len(got), 1),
            "len_ratio": round(sum(got) / max(1, sum(target)), 3),
        })
    return out


def main() -> None:
    from backend.config import DATA_DIR, MODEL_DIR

    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--corpus", type=Path, default=DATA_DIR / "corpus" / "vidub_train.jsonl")
    ap.add_argument("--dev", type=int, default=500, help="số cặp dev (phải khớp --dev lúc huấn luyện); 0 = bỏ qua")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--skip-base", action="store_true")
    ap.add_argument("--out", type=Path, default=isochron.adapter_dir(MODEL_DIR) / "eval_gold.json")
    args = ap.parse_args()

    result: dict = {"gold": [], "dev": []}
    # nạp lần lượt từng mô hình để không giữ hai bản 2,4 GB cùng lúc trên GPU 8 GB
    for kind in ("base", "lora"):
        if kind == "base" and args.skip_base:
            continue
        if kind == "lora" and not isochron.has_adapter(MODEL_DIR):
            print("Chưa có adapter ở", isochron.adapter_dir(MODEL_DIR))
            continue
        tr = Translator(lora=kind == "lora")
        b, l = (tr, None) if kind == "base" else (None, tr)
        result["gold"] += eval_gold(b, l)
        if args.dev:
            result["dev"] += eval_dev(b, l, args.corpus, args.dev, args.seed)
        tr.close()

    print(f"\nBộ gold ({GOLD / 'gold.json'}):")
    print(f"{'bản dịch':16s} {'BLEU':>6s} {'chrF':>6s} {'vượt khung (đơn vị đọc)':>26s} {'vượt (dòng)':>13s} {'âm tiết/ref':>12s}")
    for r in result["gold"]:
        print(f"{r['name']:16s} {r['bleu']:6.1f} {r['chrf']:6.1f} "
              f"{r['over_units']:>10d}/{r['units']:<3d} = {r['over_units_pct']:5.1f}% "
              f"{r['over_lines']:>8d}/{r['lines']:<4d} {r['syllables'] / r['ref_syllables']:12.2f}")
    if result["dev"]:
        print(f"\nTập dev ({args.dev} cặp OpenSubtitles không tham gia huấn luyện):")
        print(f"{'bản dịch':40s} {'BLEU':>6s} {'chrF':>6s} {'lệch TB':>8s} {'±1 âm tiết':>11s} {'dài hơn n':>10s} {'dài/n':>6s}")
        for r in result["dev"]:
            print(f"{r['name']:40s} {r['bleu']:6.1f} {r['chrf']:6.1f} {r['mae_syllables']:8.2f} "
                  f"{r['within_1_pct']:10.1f}% {r['over_target_pct']:9.1f}% {r['len_ratio']:6.2f}")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print("\nĐã ghi", args.out)


if __name__ == "__main__":
    main()
