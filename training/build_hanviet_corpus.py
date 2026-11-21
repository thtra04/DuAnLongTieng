"""Dữ liệu huấn luyện lại LoRA Trung → Việt cho phần âm Hán Việt → data/corpus/vidub_train_hv.jsonl.

    data/_train_venv/Scripts/python -I -X utf8 training/build_hanviet_corpus.py data/_opus/dl/vi-zh_CN.txt.zip

Adapter Trung → Việt bản đầu (11/11/2026) học 300.000 cặp phụ đề ngẫu nhiên: NLLB vẫn bịa
tên ("Roku", "Hồ Chí Minh" cho 郎君, 霍娘) và dịch sát chữ cách xưng hô cổ trang. Bản này
thêm vào đúng 300.000 cặp cũ (trừ 500 cặp dev cũ, để còn so sánh) các cặp OpenSubtitles mà
phía tiếng Việt đọc theo âm Hán Việt (tìm bằng `hanviet.harvest`):

* tên riêng (chữ hoa: 柳金虎 → Liễu Kim Hổ, 霍 → Hoắc), hoặc
* cách xưng hô cổ trang trong danh sách `XUNG_HO` bên dưới (郎君 → lang quân, 夫人 → phu nhân…).

Một nửa số cặp đó được **cài sẵn cụm Hán Việt vào câu gốc** đúng như app làm với Google/NLLB
(`translate.apply_glossary`: "郎君好大的威风" → "lang quân 好大的威风"), để mô hình học chép
nguyên cụm đã cài thay vì dịch lại nó. Câu trùng / gần trùng bộ gold bị loại.
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from backend.core import hanviet, translate  # noqa: E402

import build_corpus  # noqa: E402
import prepare_opus  # noqa: E402
import train_nllb_lora as T  # noqa: E402

# Cách xưng hô / chức danh cổ trang thường gặp; chỉ chọn câu mà bản Việt đọc đúng âm Hán Việt
XUNG_HO = set("""郎君 夫君 相公 娘子 小娘子 夫人 老爷 少爷 小姐 姑娘 公子 大人 在下 本宫 臣妾 奴婢 奴家 民女
陛下 殿下 皇上 皇后 太后 王爷 贵妃 公主 将军 师父 师兄 师姐 师弟 师妹 前辈 晚辈 掌柜 大夫 知府 县令 秀才
掌门 宗主 娘娘 主子 姐姐 妹妹 哥哥 兄长 小弟 夫子 先生 老夫 贫道 贫僧 施主 大侠 少侠 女侠 寡人 朕""".split())


def main() -> None:
    from backend.config import DATA_DIR

    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("zip", type=Path, help="OPUS OpenSubtitles vi-zh_CN.txt.zip")
    ap.add_argument("--base", type=Path, default=DATA_DIR / "corpus" / "vidub_train.jsonl")
    ap.add_argument("--out", type=Path, default=DATA_DIR / "corpus" / "vidub_train_hv.jsonl")
    ap.add_argument("--holdout", type=Path, default=ROOT / "data" / "_bench" / "gold" / "gold.json")
    ap.add_argument("--max", type=int, default=60_000, help="số cặp Hán Việt tối đa (lấy mẫu ngẫu nhiên)")
    ap.add_argument("--inject-rate", type=float, default=0.5)
    ap.add_argument("--dev", type=int, default=500, help="số cặp dev của adapter cũ — bỏ khỏi dữ liệu mới")
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    base = T.load_pairs(args.base, {"extra"}, 0, args.seed, "zh")
    old_dev, old_train = base[: args.dev], base[args.dev:]
    used = {p["src"] for p in base}
    gold = json.loads(args.holdout.read_text(encoding="utf-8"))
    held_exact = {g["text"] for g in gold}
    held_grams = set().union(*(build_corpus._bigrams(g["text"]) for g in gold))

    rng = random.Random(args.seed)
    sample: list[dict] = []
    seen: set[str] = set()
    total = kept = 0
    for zh, vi in prepare_opus.read_pairs(args.zip, "zh"):
        total += 1
        zh, vi = prepare_opus.clean(zh), prepare_opus.clean(vi)
        if not prepare_opus.keep(zh, vi) or zh in used or zh in seen:
            continue
        if zh in held_exact or build_corpus.near_holdout(zh, held_grams):
            continue
        terms = [(z, v) for z, v in hanviet.harvest(zh, vi) if v[:1].isupper() or z in XUNG_HO]
        if not terms:
            continue
        seen.add(zh)
        kept += 1
        row = {"zh": zh, "vi": vi, "terms": terms}
        if len(sample) < args.max:
            sample.append(row)
        else:
            j = rng.randrange(kept)
            if j < args.max:
                sample[j] = row
        if total % 2_000_000 == 0:
            print(f"  đã đọc {total:,} dòng, cặp có cụm Hán Việt {kept:,}", flush=True)

    rng.shuffle(sample)
    injected = 0
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", encoding="utf-8", newline="\n") as f:
        for p in old_train:
            f.write(json.dumps({"src": p["src"], "tgt": p["tgt"], "src_lang": "zh", "tgt_lang": "vi",
                                "origin": "extra"}, ensure_ascii=False) + "\n")
        for row in sample:
            src = row["zh"]
            if rng.random() < args.inject_rate:
                src = translate.apply_glossary([src], sorted(row["terms"], key=lambda t: -len(t[0])))[0][0]
                injected += 1
            f.write(json.dumps({"src": src, "tgt": row["vi"], "src_lang": "zh", "tgt_lang": "vi",
                                "origin": "hanviet"}, ensure_ascii=False) + "\n")
    print(f"Đọc {total:,} cặp, {kept:,} cặp có tên riêng / xưng hô đọc theo âm Hán Việt; lấy {len(sample):,} "
          f"({injected:,} cặp cài sẵn cụm vào câu gốc) + {len(old_train):,} cặp cũ -> {args.out}")
    print(f"Bỏ {len(old_dev)} cặp dev của adapter cũ để còn so hai bản trên cùng tập dev.")


if __name__ == "__main__":
    main()
