"""Dựng bảng âm Hán Việt + pinyin cho từng chữ Hán → backend/core/hanviet_data.tsv.

    curl -L -o data/_hanviet_src/hanviet.csv https://raw.githubusercontent.com/ph0ngp/hanviet-pinyin-wordlist/main/hanviet.csv
    curl -L -o data/_unihan/Unihan.zip https://www.unicode.org/Public/UCD/latest/ucd/Unihan.zip
    python -I training/build_hanviet.py data/_hanviet_src/hanviet.csv data/_unihan/Unihan.zip

Hai nguồn, đều cho phép dùng lại (ghi chú bản quyền nằm ở đầu tệp kết quả):

* `hanviet.csv` (Phong Phan, giấy phép MIT) — âm Hán Việt của ~9.000 chữ **phồn thể**, tách theo
  từng âm pinyin (長 cháng = trường, zhǎng = trưởng). Soạn từ Thiều Chửu, Trần Văn Chánh,
  Nguyễn Quốc Hùng, hvdic.thivien.net. Đã thử trường kVietnamese của Unihan trước: thiếu
  cả 春 何 胡 劉 và lẫn âm Nôm (朱 "cho", 徐 "chờ") nên không dùng.
* Unicode Han Database (Unicode License v3) — pinyin mọi chữ (kMandarin, kHanyuPinyin,
  kXHC1983) và cặp giản thể ↔ phồn thể: chữ giản thể mượn âm của chữ phồn thể (刘 → 劉 → lưu).

Kèm một dòng `#viet` liệt kê các âm pinyin cũng là từ tiếng Việt thường gặp (an, ba, lang…),
đếm trên phía tiếng Việt của corpus Trung – Việt: gặp các âm này một mình thì không coi là
phiên âm sót lại. Chạy lại script là ra đúng tệp cũ (không có ngẫu nhiên).
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import re
import sys
import unicodedata
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "backend" / "core" / "hanviet_data.tsv"
_CP = re.compile(r"U\+([0-9A-F]{4,6})")
_HV = re.compile(r"'([^']+)'")
MIT = ("hanviet.csv: Copyright (c) 2024 Phong Phan — MIT License "
       "(https://github.com/ph0ngp/hanviet-pinyin-wordlist). Permission is hereby granted, free of charge, "
       "to any person obtaining a copy of this software and associated documentation files (the \"Software\"), "
       "to deal in the Software without restriction, including without limitation the rights to use, copy, modify, "
       "merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom "
       "the Software is furnished to do so, subject to the following conditions: The above copyright notice and "
       "this permission notice shall be included in all copies or substantial portions of the Software. "
       "THE SOFTWARE IS PROVIDED \"AS IS\", WITHOUT WARRANTY OF ANY KIND.")
UNICODE = ("Unihan (pinyin, giản thể ↔ phồn thể): © Unicode, Inc., Unicode License v3 "
           "(https://www.unicode.org/license.txt).")
# Âm tiết tiếng Việt viết bằng chữ ASCII (không dấu): phụ âm đầu + vần. Không có f j w z,
# không có "zh", "sh", "ou", "uo", "ie"… — những thứ chỉ pinyin mới có.
_ONSET = "(?:ngh|ng|nh|ch|gh|gi|kh|ph|qu|th|tr|[bcdghklmnprstvx])?"
_RHYME = ("(?:a|ac|ach|ai|am|an|ang|anh|ao|ap|at|au|ay|e|ec|em|en|eng|eo|ep|et|i|ia|ich|im|in|inh|ip|it|iu|"
          "o|oa|oac|oach|oai|oam|oan|oang|oanh|oap|oat|oay|oc|oe|oen|oet|oi|om|on|ong|oong|op|ot|"
          "u|ua|uc|ui|um|un|ung|up|ut|uy|uya|uych|uyn|uynh|uyt|y)")
VIET_SYLLABLE = re.compile(_ONSET + _RHYME)


def toneless(py: str) -> str:
    """'zhǎng' / 'zhang3' / 'nu:3' / 'lǜ' → 'zhang' / 'zhang' / 'nu' / 'lu'."""
    s = unicodedata.normalize("NFD", py.lower().replace("u:", "u"))
    s = "".join(ch for ch in s if unicodedata.category(ch) != "Mn")
    return re.sub(r"[^a-z]", "", s.replace("ü", "u"))


def read_unihan(path: Path):
    # kMandarin trước (âm thường gặp nhất), rồi kXHC1983, kHanyuPinyin
    fields: dict[str, dict[str, list[str]]] = {"kMandarin": {}, "kXHC1983": {}, "kHanyuPinyin": {}}
    trad: dict[str, list[str]] = {}
    simp: dict[str, list[str]] = {}
    with zipfile.ZipFile(path) as z:
        for name in ("Unihan_Readings.txt", "Unihan_Variants.txt"):
            with z.open(name) as f:
                for ln in io.TextIOWrapper(f, encoding="utf-8"):
                    if not ln.startswith("U+"):
                        continue
                    cp, field, value = ln.rstrip("\n").split("\t", 2)
                    ch = chr(int(cp[2:], 16))
                    if field == "kMandarin":
                        fields[field][ch] = value.split()
                    elif field in ("kHanyuPinyin", "kXHC1983"):
                        fields[field][ch] = [v for part in value.split() for v in part.split(":", 1)[-1].split(",")]
                    elif field == "kTraditionalVariant":
                        trad[ch] = [chr(int(c, 16)) for c in _CP.findall(value)]
                    elif field == "kSimplifiedVariant":
                        simp[ch] = [chr(int(c, 16)) for c in _CP.findall(value)]
    py: dict[str, list[str]] = defaultdict(list)
    for field in ("kMandarin", "kXHC1983", "kHanyuPinyin"):
        for ch, values in fields[field].items():
            for v in values:
                t = toneless(v)
                if t and t not in py[ch]:
                    py[ch].append(t)
    return py, trad, simp


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("csv", type=Path, help="hanviet.csv (ph0ngp/hanviet-pinyin-wordlist)")
    ap.add_argument("unihan", type=Path, help="Unihan.zip tải từ unicode.org")
    ap.add_argument("--corpus", type=Path, default=ROOT / "data" / "corpus" / "opus_zh_vi.jsonl",
                    help="corpus Trung – Việt để đếm âm pinyin trùng từ tiếng Việt")
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()

    py, trad, simp = read_unihan(args.unihan)

    # chữ phồn thể → [(pinyin không dấu hoặc None = mọi âm, [âm Hán Việt…])]
    entries: dict[str, list[tuple[str | None, list[str]]]] = defaultdict(list)
    with open(args.csv, encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            hv = [unicodedata.normalize("NFC", h).strip() for h in _HV.findall(row["hanviet"])]
            hv = [h for h in hv if h]
            if hv and len(row["char"]) == 1:
                entries[row["char"]].append((None if row["pinyin"].strip() == "*" else toneless(row["pinyin"]), hv))

    def expand(ch: str, src: str) -> dict[str, list[str]]:
        """pinyin → âm Hán Việt của chữ `ch`, lấy theo dòng của chữ phồn thể `src`."""
        out: dict[str, list[str]] = {}
        for p, hv in entries[src]:
            for q in ([p] if p else (py.get(src) or py.get(ch) or ["?"])):
                out.setdefault(q, [])
                out[q] += [h for h in hv if h not in out[q]]
        return out

    table: dict[str, dict[str, list[str]]] = {}
    for ch in set(entries) | set(trad) | set(simp):
        # chính nó + các chữ phồn thể tương ứng (干 → 乾 幹); chữ phồn thể chưa có dòng nào
        # thì mượn chữ giản thể của nó
        sources = ([ch] if ch in entries else []) + [t for t in trad.get(ch, []) if t != ch and t in entries]
        if not sources:
            sources = [s for s in simp.get(ch, []) if s in entries]
        merged: dict[str, list[str]] = {}
        for src in sources:
            for p, hv in expand(ch, src).items():
                merged.setdefault(p, [])
                merged[p] += [h for h in hv if h not in merged[p]]
        if merged:
            table[ch] = merged

    def default(ch: str) -> str:
        m = table[ch]
        for p in py.get(ch, []):  # âm pinyin thường gặp nhất của chính chữ đó
            if p in m:
                return m[p][0]
        return next(iter(m.values()))[0]

    # Âm pinyin cũng là âm tiết tiếng Việt viết không dấu (an, ba, lang, long…): hợp chính tả
    # tiếng Việt VÀ gặp ở dạng chữ thường ≥ 20 lần phía tiếng Việt của corpus (chỉ đếm thì
    # lẫn cả "fan", "jun" của tiếng Anh, tên phiên âm).
    syllables = {p for m in table.values() for p in m if p != "?" and VIET_SYLLABLE.fullmatch(p)}
    words: Counter = Counter()
    if args.corpus.exists():
        for ln in args.corpus.read_text(encoding="utf-8").splitlines():
            vi = unicodedata.normalize("NFC", json.loads(ln)["tgt"])
            words.update(w for w in re.findall(r"[a-zà-ỹđ]+", vi) if w in syllables)
    viet = sorted(w for w, n in words.items() if n >= 20)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", encoding="utf-8", newline="\n") as f:
        f.write(f"# Âm Hán Việt + pinyin từng chữ Hán. Dựng bằng training/build_hanviet.py từ: {MIT} {UNICODE}\n")
        f.write("# cột: chữ <TAB> âm Hán Việt thường dùng <TAB> pinyin=âm/âm;pinyin=âm…\n")
        f.write("#viet\t" + ",".join(viet) + "\n")
        for ch in sorted(table):
            m = table[ch]
            f.write(f"{ch}\t{default(ch)}\t" + ";".join(f"{p}={'/'.join(hv)}" for p, hv in m.items()) + "\n")
    print(f"{len(table):,} chữ có âm Hán Việt ({sum(1 for c in table if c in entries):,} có sẵn trong hanviet.csv, "
          f"phần còn lại mượn chữ phồn/giản thể); {len(viet)} âm pinyin cũng là từ tiếng Việt -> {args.out}")


if __name__ == "__main__":
    main()
