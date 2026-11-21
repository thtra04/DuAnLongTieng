"""HP-4 — đo NLLB gốc so với NLLB + LoRA đẳng thời: bộ gold Trung → Việt và bảng chéo nhiều thứ tiếng.

    python training/eval_nllb_lora.py              # cả hai phần
    python training/eval_nllb_lora.py --no-cross   # chỉ bộ gold (như 11/11/2026)
    python data/_bench/score_vi.py data/_bench/gold/nllb_*_vi.json   # bảng BLEU/chrF chung

**Bộ gold** (271 câu thoại cổ trang tiếng Trung, dịch TỪNG DÒNG bằng chính
`translate._translate_nllb` của app):

    nllb_goc        NLLB-200 distilled 600M nguyên bản
    nllb_goc_luat   … rồi rút gọn bằng luật tiếng Việt (HP-5, `shorten.py`)
    nllb_lora       NLLB + LoRA Trung → Việt, không gắn token ngân sách
    nllb_lora_len   … rồi câu nào vượt khung thì dịch lại từng dòng với token `<len:n>`
    nllb_lora_app   … như trên nhưng bằng bộ siết của app (`translate.make_tightener`)

Tỉ lệ vượt khung đo bằng chính `budget.assess` / `budget.over_budget` của app (theo
đơn vị đọc TTS), kèm một số đo theo từng dòng để nhìn rõ hơn (68 đơn vị là ít).

**Bảng chéo** (giả thuyết H1): mỗi adapter (Trung, Hàn, Nhật, Anh — mỗi cái chỉ học một
thứ tiếng nguồn) được thử trên tập kiểm tra của mọi thứ tiếng, gồm cả nhóm B (Pháp, Nga,
Thái) không adapter nào học. Ngân sách n = số âm tiết của bản tham chiếu; đo độ lệch.
Adapter X trên tiếng Y ≠ X là dịch "zero-shot" — nếu token vẫn điều khiển được độ dài
thì khả năng đó gắn với phía tiếng Việt, không phải với ngôn ngữ nguồn đã học.
Tập kiểm tra loại mọi câu mà bản Việt trùng với câu Việt trong dữ liệu huấn luyện của bất
kỳ adapter nào (OpenSubtitles có cùng một phụ đề Việt gióng với nhiều thứ tiếng).
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import re
import sys
import time
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from backend.core import budget, duration, isochron, shorten, translate  # noqa: E402
from backend.core.subtitles import Cue  # noqa: E402

import train_nllb_lora as T  # noqa: E402

GOLD = ROOT / "data" / "_bench" / "gold"
TAG = ""                            # hậu tố tên tệp bản dịch khi đo adapter thử (--zh-adapter), để không đè bản thật
GROUP_A = isochron.LANGS            # có adapter riêng
GROUP_B = ("fr", "ru", "th")        # không adapter nào học — chỉ để kiểm thử H1
norm = lambda s: unicodedata.normalize("NFC", s or "").strip()  # noqa: E731


def vi_key(text: str) -> str:
    """Khoá so trùng câu Việt: chữ thường, bỏ dấu câu."""
    return " ".join(re.findall(r"\w+", norm(text).lower()))


def use_zh_adapter(path: Path | None) -> None:
    """Cho mọi chỗ (app lẫn script) đọc adapter Trung → Việt ở `path` — để đo bản thử mà chưa thay bản thật."""
    if not path:
        return
    orig = isochron.adapter_dir
    isochron.adapter_dir = lambda model_dir, lang="zh": Path(path) if lang == "zh" else orig(model_dir, lang)


class Translator:
    """Gọi đúng đường mã của app (`translate._translate_nllb`), ép dùng một adapter hoặc không adapter nào.

    Nạp NLLB một lần kèm mọi adapter có sẵn; "không adapter" = tắt adapter (đúng như app làm
    với cặp ngôn ngữ chưa có adapter), nên mọi cột cùng một mô hình gốc.
    """

    def __init__(self):
        os.environ["VSUB_NLLB_LORA"] = "1"
        translate._nllb_cache.clear()
        self.loaded = translate._load_nllb()[3]

    def __call__(self, texts: list[str], src: str = "zh", adapter: str | None = None,
                 budgets: list[int | None] | None = None) -> list[str]:
        if adapter and adapter not in self.loaded:
            raise RuntimeError(f"Chưa nạp được adapter {adapter} (có: {self.loaded})")
        orig = translate.lora_for
        translate.lora_for = lambda s, t: adapter  # app chọn adapter qua hàm này
        try:
            return translate._translate_nllb(texts, src, "vi", budgets=budgets)
        finally:
            translate.lora_for = orig

    def close(self) -> None:
        translate._nllb_cache.clear()


# ------------------------------------------------------------------ bộ gold Trung → Việt

def token_tightener(cues: list[Cue], tr: Translator):
    """Bộ siết HP-4: dịch lại từng dòng của đơn vị vượt khung với token ngân sách nhỏ hơn."""

    def tighten(requests: list[dict]) -> list:
        jobs = []
        for r in requests:
            scale = r["target_syllables"] / max(1, r["syllables"])
            for i, piece in zip(r["cues"], r["pieces"]):
                jobs.append((cues[i].text, max(1, int(duration.syllables(piece) * scale))))
        new = iter(tr([j[0] for j in jobs], "zh", "zh", [j[1] for j in jobs]))
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
    (GOLD / f"{name}{TAG}_vi.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
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


def eval_gold(tr: Translator) -> list[dict]:
    gold = json.loads((GOLD / "gold.json").read_text(encoding="utf-8"))
    ref = {int(ln.split("\t")[0]): ln.split("\t", 1)[1].strip()
           for ln in (GOLD / "ref_vi.tsv").read_text(encoding="utf-8").splitlines() if ln.strip()}
    model = duration.default_model()
    texts = [g["text"] for g in gold]
    fresh = lambda vi: [Cue(g["start"], g["end"], g["text"], v) for g, v in zip(gold, vi)]  # noqa: E731
    out = []
    cues = fresh(tr(texts, "zh", None))
    out.append(measure("nllb_goc", cues, gold, ref, model))
    cues = copy.deepcopy(cues)
    budget.run_loop(cues, shorten.make_tightener(), model)
    out.append(measure("nllb_goc_luat", cues, gold, ref, model))
    if "zh" not in tr.loaded:
        return out
    cues = fresh(tr(texts, "zh", "zh"))
    out.append(measure("nllb_lora", cues, gold, ref, model))
    cues = copy.deepcopy(cues)
    stats = budget.run_loop(cues, token_tightener(cues, tr), model)
    row = measure("nllb_lora_len", cues, gold, ref, model)
    row["loop"] = {k: stats[k] for k in ("over_before", "over_after", "passes", "tightened")}
    out.append(row)
    # đúng bộ siết app dùng: dịch lại CẢ đơn vị đọc với token rồi chia lại vào từng dòng
    cues = fresh([r["vi"] for r in json.loads((GOLD / f"nllb_lora{TAG}_vi.json").read_text(encoding="utf-8"))])
    budget.run_loop(cues, translate.make_tightener("nllb", target="vi", source="zh"), model)
    out.append(measure("nllb_lora_app", cues, gold, ref, model))
    return out


# ------------------------------------------------------------------ bảng chéo nhiều thứ tiếng

def test_sets(data_dir: Path, model_dir: Path, n_dev: int, n_b: int, seed: int,
              also_exclude: list[Path] = ()) -> tuple[dict, dict]:
    """Tập kiểm tra từng thứ tiếng, đã loại câu Việt trùng dữ liệu huấn luyện của mọi adapter.

    Nhóm A: đúng `n_dev` cặp dev đầu tiên mà lúc huấn luyện đã tách ra (phải khớp `--dev`).
    Nhóm B: `n_b` cặp đầu của tệp đã lọc (prepare_opus.py --max 2000).
    `also_exclude`: thêm corpus khác (ví dụ dữ liệu của một adapter thử) — loại mọi câu Việt có trong đó.
    """
    trained: set[str] = set()
    for path in also_exclude:
        with open(path, encoding="utf-8") as f:
            trained |= {vi_key(json.loads(ln)["tgt"]) for ln in f if ln.strip()}
    raw: dict[str, list[dict]] = {}
    for lang in GROUP_A:
        corpus = T.default_corpus(data_dir, lang)
        if not corpus.exists():
            continue
        pairs = T.load_pairs(corpus, {"extra"}, 0, seed, lang)
        raw[lang] = pairs[:n_dev]
        if isochron.has_adapter(model_dir, lang):
            trained |= {vi_key(p["tgt"]) for p in pairs[n_dev:]}
            # adapter học trên corpus khác (ví dụ vidub_train_hv.jsonl = bản cũ + cặp Hán Việt): loại mọi câu của corpus đó
            meta = isochron.adapter_dir(model_dir, lang) / "train_meta.json"
            other = data_dir / "corpus" / json.loads(meta.read_text(encoding="utf-8")).get("corpus", corpus.name) \
                if meta.is_file() else corpus
            if other != corpus and other.is_file():
                with open(other, encoding="utf-8") as f:
                    trained |= {vi_key(json.loads(ln)["tgt"]) for ln in f if ln.strip()}
    for lang in GROUP_B:
        corpus = data_dir / "corpus" / f"opus_{lang}_vi.jsonl"
        if corpus.exists():
            raw[lang] = T.load_pairs(corpus, None, 0, seed, lang)
    sets, info = {}, {}
    for lang, pairs in raw.items():
        keep = [p for p in pairs if vi_key(p["tgt"]) not in trained]
        sets[lang] = keep[: (n_b if lang in GROUP_B else n_dev)]
        # nhóm A: bỏ hẳn câu trùng trong n_dev cặp dev; nhóm B: lấy n_b cặp đầu trong số không trùng
        info[lang] = {"pool": len(pairs), "dropped_overlap": len(pairs) - len(keep), "after": len(sets[lang])}
    return sets, info


def scores(hyp: list[str], ref: list[str], want: list[int]) -> dict:
    import sacrebleu

    hyp = [norm(h) for h in hyp]
    got = [duration.syllables(h) for h in hyp]
    diff = [abs(g - t) for g, t in zip(got, want)]
    return {
        "n": len(hyp),
        "bleu": round(sacrebleu.corpus_bleu(hyp, [ref]).score, 1),
        "chrf": round(sacrebleu.corpus_chrf(hyp, [ref]).score, 1),
        "mae_syllables": round(sum(diff) / len(diff), 2),
        "within_1_pct": round(100 * sum(d <= 1 for d in diff) / len(diff), 1),
        "over_target_pct": round(100 * sum(g > t for g, t in zip(got, want)) / len(got), 1),
        # "câu phải nén" (MT-4/MT-5) theo cùng ngưỡng của app: dài hơn ngân sách quá budget.TOLERANCE
        "over_tol_pct": round(100 * sum(g > t * (1 + budget.TOLERANCE) for g, t in zip(got, want)) / len(got), 1),
        "len_ratio": round(sum(got) / max(1, sum(want)), 3),
    }


def eval_cross(tr: Translator, sets: dict, out_dir: Path, adapters: tuple[str, ...] | None = None) -> list[dict]:
    """Mỗi tập: NLLB gốc; adapter của chính thứ tiếng đó không token; mọi adapter với `<len:n>`."""
    rows = []
    out_dir.mkdir(parents=True, exist_ok=True)
    use = [a for a in tr.loaded if not adapters or a in adapters]
    for lang, pairs in sets.items():
        src = [p["src"] for p in pairs]
        ref = [norm(p["tgt"]) for p in pairs]
        want = [duration.syllables(r) for r in ref]
        runs = [("goc", None, None)]
        if lang in use:
            runs.append((f"{lang}", lang, None))
        runs += [(f"{a}+len", a, want) for a in use]
        hyps = {}
        for name, adapter, budgets in runs:
            t0 = time.monotonic()
            hyp = tr(src, lang, adapter, budgets)
            hyps[name] = hyp
            row = {"lang": lang, "group": "A" if lang in GROUP_A else "B", "run": name, "adapter": adapter,
                   "token": budgets is not None, "zero_shot": bool(adapter) and adapter != lang,
                   **scores(hyp, ref, want), "seconds": round(time.monotonic() - t0, 1)}
            rows.append(row)
            print(f"  {lang} {name:8s} BLEU {row['bleu']:5.1f} chrF {row['chrf']:5.1f} "
                  f"±1 âm tiết {row['within_1_pct']:5.1f}% dài hơn n {row['over_target_pct']:5.1f}% "
                  f"phải nén (>n+5%) {row['over_tol_pct']:5.1f}% ({row['seconds']:.0f}s)", flush=True)
        (out_dir / f"{lang}.json").write_text(json.dumps(
            [{"src": s, "ref": r, **{k: v[i] for k, v in hyps.items()}} for i, (s, r) in enumerate(zip(src, ref))],
            ensure_ascii=False, indent=1), encoding="utf-8")
    return rows


def print_cross(rows: list[dict], info: dict) -> None:
    langs = list(dict.fromkeys(r["lang"] for r in rows))
    adapters = list(dict.fromkeys(r["adapter"] for r in rows if r["token"]))
    get = {(r["lang"], r["run"]): r for r in rows}
    for key, title in (("within_1_pct", "Tỉ lệ câu lệch không quá 1 âm tiết so với ngân sách n (%)"),
                       ("over_tol_pct", f"Tỉ lệ câu phải nén — dài hơn n quá {budget.TOLERANCE:.0%} (%)")):
        print(f"\n{title}, * = adapter học đúng thứ tiếng đó:")
        print(f"{'tập':6s} {'cặp':>5s} {'gốc':>7s} " + " ".join(f"{a + '+len':>9s}" for a in adapters))
        for lang in langs:
            cells = []
            for a in adapters:
                r = get.get((lang, f"{a}+len"))
                cells.append(f"{r[key]:8.1f}{'*' if a == lang else ' '}" if r else f"{'—':>9s}")
            print(f"{lang:6s} {info[lang]['after']:5d} {get[(lang, 'goc')][key]:7.1f} " + " ".join(cells))
    print("\nchrF (gốc / adapter cùng thứ tiếng không token / các adapter có token):")
    for lang in langs:
        own = get.get((lang, lang))
        cells = " ".join(f"{a}+len {get[(lang, f'{a}+len')]['chrf']:4.1f}" for a in adapters if (lang, f"{a}+len") in get)
        print(f"{lang:6s} gốc {get[(lang, 'goc')]['chrf']:4.1f}"
              + (f"  {lang} {own['chrf']:4.1f}" if own else "") + "  " + cells)


def main() -> None:
    from backend.config import DATA_DIR, MODEL_DIR

    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--no-gold", action="store_true", help="bỏ phần bộ gold Trung → Việt")
    ap.add_argument("--no-cross", action="store_true", help="bỏ bảng chéo nhiều thứ tiếng")
    ap.add_argument("--dev", type=int, default=500, help="số cặp dev mỗi thứ tiếng nhóm A (phải khớp --dev lúc huấn luyện)")
    ap.add_argument("--n-b", type=int, default=500, help="số cặp kiểm tra mỗi thứ tiếng nhóm B")
    ap.add_argument("--langs", default="", help="chỉ đo các tập này, ví dụ 'ja,fr' (mặc định: mọi tập có sẵn)")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--adapters", default="", help="bảng chéo chỉ chạy các adapter này, ví dụ 'zh' (mặc định: mọi adapter đã nạp)")
    ap.add_argument("--also-exclude", type=Path, action="append", default=[],
                    help="loại thêm mọi câu Việt có trong corpus này khỏi tập kiểm tra (lặp được)")
    ap.add_argument("--zh-adapter", type=Path, help="đo adapter Trung → Việt ở thư mục khác (bản thử) thay cho bản app đang dùng")
    ap.add_argument("--out", type=Path, help="mặc định <thư mục adapter Trung>/eval_gold.json")
    ap.add_argument("--cross-out", type=Path, default=ROOT / "data" / "_bench" / "nllb_lora_cross.json")
    args = ap.parse_args()
    use_zh_adapter(args.zh_adapter)
    args.out = args.out or isochron.adapter_dir(MODEL_DIR, "zh") / "eval_gold.json"
    if args.zh_adapter:
        global TAG
        TAG = "_" + (args.zh_adapter.name.replace(isochron.ADAPTER_DIRNAME, "").strip("_") or "thu")

    tr = Translator()
    print("Adapter đã nạp:", ", ".join(tr.loaded) or "không có")
    if not args.no_gold:
        rows = eval_gold(tr)
        print(f"\nBộ gold ({GOLD / 'gold.json'}):")
        print(f"{'bản dịch':16s} {'BLEU':>6s} {'chrF':>6s} {'vượt khung (đơn vị đọc)':>26s} {'vượt (dòng)':>13s} {'âm tiết/ref':>12s}")
        for r in rows:
            print(f"{r['name']:16s} {r['bleu']:6.1f} {r['chrf']:6.1f} "
                  f"{r['over_units']:>10d}/{r['units']:<3d} = {r['over_units_pct']:5.1f}% "
                  f"{r['over_lines']:>8d}/{r['lines']:<4d} {r['syllables'] / r['ref_syllables']:12.2f}")
        args.out.parent.mkdir(parents=True, exist_ok=True)
        old = json.loads(args.out.read_text(encoding="utf-8")) if args.out.exists() else {}
        args.out.write_text(json.dumps({**old, "gold": rows}, ensure_ascii=False, indent=1), encoding="utf-8")
        print("Đã ghi", args.out)
    if not args.no_cross:
        sets, info = test_sets(DATA_DIR, MODEL_DIR, args.dev, args.n_b, args.seed, args.also_exclude)
        if args.langs:
            want = set(args.langs.split(","))
            sets = {k: v for k, v in sets.items() if k in want}
        print("\nTập kiểm tra (sau khi loại câu Việt trùng dữ liệu huấn luyện):",
              ", ".join(f"{k} {info[k]['after']}" for k in sets))
        adapters = tuple(a for a in args.adapters.split(",") if a) or None
        rows = eval_cross(tr, sets, args.cross_out.with_suffix(""), adapters)
        print_cross(rows, info)
        old = json.loads(args.cross_out.read_text(encoding="utf-8")) if args.cross_out.exists() else {}
        keep = [r for r in old.get("rows", []) if r["lang"] not in sets]
        args.cross_out.write_text(json.dumps({"adapters": list(adapters or tr.loaded), "sets": {**old.get("sets", {}), **info},
                                              "rows": keep + rows}, ensure_ascii=False, indent=1), encoding="utf-8")
        print("Đã ghi", args.cross_out)
    tr.close()


if __name__ == "__main__":
    main()
