"""Đo phần tự sửa âm Hán Việt trên bộ gold Trung → Việt (271 câu thoại cổ trang).

    .venv/Scripts/python training/eval_hanviet.py              # Google (dịch lại nửa sau qua mạng)
    .venv/Scripts/python training/eval_hanviet.py --nllb       # thêm NLLB gốc / NLLB + LoRA (cần GPU rảnh)

Chỉ số:
  * **Cụm Hán Việt đúng** — trong bản tham chiếu, những cụm được đọc theo âm Hán Việt
    (郎君 → lang quân, 霍 → Hoắc, 柳金虎 → Liễu Kim Hổ…, tìm bằng `hanviet.harvest`); bản dịch
    có đúng cụm đó không. Đây là thứ người dùng phàn nàn, BLEU không đo trúng.
  * **Phiên âm sót** — số đoạn pinyin trong bản dịch khớp được với chữ trong câu gốc.
  * BLEU / chrF như các bảng khác.

Cách đo công bằng cho phần tự học: chia bộ gold làm đôi theo thứ tự câu. Nửa đầu đóng vai
"tập đã làm": người dùng sửa bản Google thành bản tham chiếu, app học các chỗ sửa sang âm
Hán Việt (`hanviet.corrections`). Nửa sau đóng vai "tập mới": dịch bằng Google có cài cụm đã
học vào câu gốc, rồi sửa phiên âm sót — chỉ đo trên nửa sau. Không học gì từ nửa sau.
Bộ thuật ngữ tự học của lần đo nằm trong thư mục tạm, không đụng tới data/hanviet_learned.json.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.core import hanviet, translate  # noqa: E402

GOLD = ROOT / "data" / "_bench" / "gold"
norm = lambda s: unicodedata.normalize("NFC", s or "").strip()  # noqa: E731


def load_gold() -> tuple[list[dict], dict[int, str]]:
    gold = json.loads((GOLD / "gold.json").read_text(encoding="utf-8"))
    ref = {int(ln.split("\t")[0]): ln.split("\t", 1)[1].strip()
           for ln in (GOLD / "ref_vi.tsv").read_text(encoding="utf-8").splitlines() if ln.strip()}
    return gold, ref


def outputs(name: str) -> dict[int, str]:
    return {r["idx"]: r["vi"] for r in json.loads((GOLD / f"{name}_vi.json").read_text(encoding="utf-8"))}


def score(rows: list[dict], hyp: dict[int, str], ref: dict[int, str], terms: dict[int, list[str]]) -> dict:
    import sacrebleu

    h = [norm(hyp[r["idx"]]) for r in rows]
    rf = [norm(ref[r["idx"]]) for r in rows]
    want = [(r["idx"], t) for r in rows for t in terms[r["idx"]]]
    hit = sum(hanviet.contains(hyp[i], t) for i, t in want)
    left = sum(len(hanviet.fix_pinyin(r["text"], hyp[r["idx"]])[1]) for r in rows)
    return {"lines": len(rows), "bleu": round(sacrebleu.corpus_bleu(h, [rf]).score, 1),
            "chrf": round(sacrebleu.corpus_chrf(h, [rf]).score, 1),
            "terms": len(want), "terms_ok": hit, "terms_pct": round(100 * hit / max(1, len(want)), 1),
            "pinyin_left": left}


def fixed(rows: list[dict], hyp: dict[int, str], known: dict[str, str] | None = None) -> dict[int, str]:
    return {r["idx"]: hanviet.fix_pinyin(r["text"], hyp[r["idx"]], known)[0] for r in rows}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--nllb", action="store_true", help="đo thêm NLLB gốc và NLLB + LoRA (cần torch, GPU)")
    ap.add_argument("--zh-adapter", type=Path, action="append", default=[],
                    help="thư mục adapter Trung → Việt cần đo (lặp được); mặc định bản app đang dùng")
    ap.add_argument("--no-google", action="store_true", help="không gọi Google (dùng lại số đo cũ trong --out)")
    ap.add_argument("--out", type=Path, default=ROOT / "data" / "_bench" / "hanviet_eval.json")
    args = ap.parse_args()

    tmp = Path(tempfile.mkdtemp(prefix="hanviet-eval-"))
    hanviet.LEARNED_PATH = tmp / "learned.json"  # không đụng bộ thuật ngữ thật

    gold, ref = load_gold()
    names = hanviet.harvest_many([(g["text"], ref[g["idx"]]) for g in gold])
    known_names = {z[0] for (z, v) in names if v[:1].isupper()}
    terms = {g["idx"]: [v for _z, v in hanviet.harvest(g["text"], ref[g["idx"]], names=known_names)] for g in gold}
    half = len(gold) // 2
    first, second = gold[:half], gold[half:]
    google = outputs("google")
    gloss = outputs("google_gloss")  # Google + bộ thuật ngữ người dùng tự gõ (đo 10/2026)

    old = json.loads(args.out.read_text(encoding="utf-8")) if args.out.exists() else {}
    table: list[dict] = []

    def add(name: str, rows: list[dict], hyp: dict[int, str], part: str):
        row = {"name": name, "part": part, **score(rows, hyp, ref, terms)}
        table.append(row)
        print(f"{part:9s} {name:46s} BLEU {row['bleu']:5.1f} chrF {row['chrf']:5.1f} "
              f"cụm Hán Việt {row['terms_ok']:3d}/{row['terms']:<3d} = {row['terms_pct']:5.1f}%  "
              f"pinyin sót {row['pinyin_left']}", flush=True)

    # Học từ nửa đầu (người dùng sửa bản Google thành bản tham chiếu); chỉ đo trên nửa sau
    learned = [p for g in first for p in hanviet.corrections(g["text"], google[g["idx"]], ref[g["idx"]])]
    hanviet.learn(learned, "sửa tay")
    terms_learned = hanviet.load()
    print(f"Học từ {len(first)} câu đầu: {len(terms_learned)} cụm — "
          + ", ".join(f"{z} → {t['vi']}" for z, t in list(terms_learned.items())[:12]) + " …\n")
    known = {z: t["vi"] for z, t in terms_learned.items()}
    texts = [g["text"] for g in second]
    sent, used = translate.apply_glossary(texts, hanviet.learned_pairs(texts))
    print(f"Cài cụm đã học vào {used}/{len(texts)} câu nửa sau.\n", flush=True)

    if args.no_google:
        table += [r for r in old.get("rows", []) if r["name"].startswith("Google")]
    else:
        # 1. Chỉ có từ điển, chưa học gì: sửa phiên âm sót trên cả 271 câu
        add("Google", gold, google, "cả bộ")
        add("Google + sửa phiên âm (từ điển)", gold, fixed(gold, google), "cả bộ")
        # 2. Tự học: dịch lại nửa sau bằng Google, câu gốc đã cài cụm học ở nửa đầu
        regoogle = dict(zip([g["idx"] for g in second], translate._translate_deep(sent, "zh", "vi", "google")))
        add("Google", second, google, "nửa sau")
        add("Google + sửa phiên âm (từ điển)", second, fixed(second, google), "nửa sau")
        add("Google + cụm đã học ở nửa đầu", second, regoogle, "nửa sau")
        add("Google + cụm đã học + sửa phiên âm", second, fixed(second, regoogle, known), "nửa sau")
        add("Google + bộ thuật ngữ người dùng tự gõ (mốc)", second, gloss, "nửa sau")

    if args.nllb:
        import os

        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from eval_nllb_lora import use_zh_adapter

        os.environ["VSUB_NLLB_LORA"] = "1"
        for k, path in enumerate(args.zh_adapter or [None]):
            if path:
                use_zh_adapter(path)
            translate._nllb_cache.clear()
            loaded = translate._load_nllb()[3]
            orig = translate.lora_for
            label = f"NLLB + LoRA ({Path(path).name})" if path else "NLLB + LoRA"
            for adapter in ((None,) if k == 0 else ()) + (("zh",) if "zh" in loaded else ()):
                translate.lora_for = lambda s, t, a=adapter: a
                tag = label if adapter else "NLLB gốc"
                plain = dict(zip([g["idx"] for g in second], translate._translate_nllb(texts, "zh", "vi")))
                inj = dict(zip([g["idx"] for g in second], translate._translate_nllb(sent, "zh", "vi")))
                add(tag, second, plain, "nửa sau")
                add(f"{tag} + cụm đã học + sửa phiên âm", second, fixed(second, inj, known), "nửa sau")
            translate.lora_for = orig
    elif args.no_google:
        table += [r for r in old.get("rows", []) if not r["name"].startswith("Google")]

    args.out.write_text(json.dumps({"learned_from_first_half": known, "rows": table},
                                   ensure_ascii=False, indent=1), encoding="utf-8")
    print("\nĐã ghi", args.out)


if __name__ == "__main__":
    main()
