"""Prepare separate MT and spoken-script supervision without opening studio projects."""
from __future__ import annotations

import argparse
import itertools
import json
import random
import re
import unicodedata
from collections import Counter, defaultdict
from difflib import SequenceMatcher
from pathlib import Path

from training.prepare_opus import clean, keep_lang, read_pairs

from backend.core.duration import syllables


def key(text):
    return "".join(re.findall(r"\w+", unicodedata.normalize("NFKC", text).casefold()))


def read_jsonl(path):
    with path.open(encoding="utf-8-sig") as f:
        return [json.loads(line) for line in f if line.strip()]


def terms(row):
    return {key(row[k]) for k in ("src", "tgt", "spoken") if row.get(k)}


def split_reviewed(rows, lang, *, seed=42, protected=()):
    """Keep entire films in one split. Test beats dev beats train on duplicate text."""
    films = defaultdict(list)
    for i, row in enumerate(rows, 1):
        if (not isinstance(row, dict) or row.get("src_lang") != lang or row.get("tgt_lang") != "vi"
                or any(not isinstance(row.get(k), str) or not key(row[k]) for k in ("film", "src", "tgt", "spoken"))
                or type(row.get("cap")) is not int or not 1 <= row["cap"] <= 60):
            raise ValueError(f"Row {i}: expected film, src_lang/tgt_lang, src/tgt/spoken and an integer cap (1..60).")
        checks = row.get("checks", [])
        if not isinstance(checks, list) or any(not isinstance(g, list) or not g
                                                or any(not isinstance(s, str) or not s.strip() for s in g) for g in checks):
            raise ValueError(f"Row {i}: checks must be a list of synonym lists.")
        film = " ".join(unicodedata.normalize("NFKC", row["film"]).casefold().split())
        films[film].append({"film": film, **{k: row[k] for k in ("src", "tgt", "spoken", "cap", "checks") if k in row}})
    names = sorted(films)
    if len(names) < 3:
        raise ValueError("Need at least three distinct films for train, development and blind test.")
    random.Random(seed).shuffle(names)
    n = max(1, round(len(names) * .2))
    splits = {}
    seen = set().union(*(terms(r) for r in protected))
    for split, group in (("test", names[:n]), ("dev", names[n:2*n]), ("train", names[2*n:])):
        accepted = []
        for film in group:
            for row in films[film]:
                keys = terms(row)
                if keys.isdisjoint(seen):
                    accepted.append(row)
                    seen.update(keys)
        if not accepted:
            raise ValueError(f"No disjoint rows left for {split}; add new films or dialogue.")
        splits[split] = accepted
    return splits


def write_reviewed_splits(out, splits, lang):
    out.mkdir(parents=True, exist_ok=False)

    def write(name, rows):
        with (out / f"{name}.jsonl").open("x", encoding="utf-8") as f:
            for row in rows:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")

    for kind, rows in splits.items():
        if kind in ("dev", "test"):
            write(kind, rows)
        if kind in ("train", "dev"):
            for task, a, b, src in (("meaning", "src", "tgt", lang), ("spoken", "tgt", "spoken", "vi")):
                write(f"{task}_{kind}", (dict(src=r[a], tgt=r[b], src_lang=src, tgt_lang="vi", origin="reviewed",
                                              **({"cap": r["cap"]} if task == "spoken" else {}))
                                         for r in rows))


# Invert an equivalent phrase to create a longer input. The target is always
# the original subtitle, not unreviewed machine translation or a truncated line.
EXPAND = [(re.compile(r"\b" + a + r"\b", re.I), b) for a, b in (
    ("hôm nay", "ngày hôm nay"), ("hôm qua", "ngày hôm qua"), ("ngày mai", "ngày mai đây"),
    ("lập tức", "ngay lập tức"), ("mặc dù", "mặc dù rằng"), ("nếu", "nếu như"),
    ("mọi người", "tất cả mọi người"), ("để làm gì", "để làm cái gì"),
    ("có lẽ", "có lẽ là"), ("bây giờ", "ngay vào lúc này"), ("dường như", "có vẻ như là"),
    ("vì sao", "vì lý do gì"), ("trong khi", "trong lúc mà"), ("bao giờ", "vào lúc nào"),
)]


def expand(text, rng):
    options = [(m, b) for pat, b in EXPAND if (m := pat.search(text))]
    if not options:
        return None
    m, longer = rng.choice(options)
    if m[0][0].isupper():
        longer = longer[0].upper() + longer[1:]
    return text[:m.start()] + longer + text[m.end():]


def prepare(pairs, lang, reviewed, holdout, limit, seed):
    rng = random.Random(seed)
    banned = set().union(*(terms(r) for r in holdout))
    meaning, spoken = {}, {}

    def add(store, src, tgt, src_lang, origin, cap=None):
        a, b = key(src), key(tgt)
        if a and b and a not in banned and b not in banned:
            store.setdefault(a, dict(src=src, tgt=tgt, src_lang=src_lang, tgt_lang="vi", origin=origin,
                                     **({"cap": cap} if cap is not None else {})))

    for r in reviewed:
        if r.get("src_lang") != lang or r.get("tgt_lang") != "vi" or not r.get("src") or not r.get("tgt"):
            raise ValueError("Reviewed rows require src/tgt and the requested src_lang/tgt_lang.")
        if terms(r) & banned:
            continue
        add(meaning, r["src"], r["tgt"], lang, "reviewed")
        if r.get("spoken"):
            add(spoken, r["tgt"], r["spoken"], "vi", "reviewed", cap=r.get("cap"))

    # Two translations aligned to the very same source are weak supervision:
    # prefer near paraphrases, never assume arbitrary subtitle variants agree.
    variants = {}
    for raw_src, raw_vi in pairs:
        src, vi = clean(raw_src), clean(raw_vi)
        if not keep_lang(src, vi, lang) or {key(src), key(vi)} & banned:
            continue
        add(meaning, src, vi, lang, "opus")
        first = variants.setdefault(key(src), vi)
        if first != vi:
            long, short = sorted((first, vi), key=syllables, reverse=True)
            if (syllables(short) < syllables(long)
                    and SequenceMatcher(None, long.lower().split(), short.lower().split()).ratio() >= .76
                    and re.findall(r"\d+|\b(?:đừng|chưa|không|chẳng)\b", long.lower())
                    == re.findall(r"\d+|\b(?:đừng|chưa|không|chẳng)\b", short.lower())):
                add(spoken, long, short, "vi", "parallel-variant")

    candidates = list(meaning.values())
    rng.shuffle(candidates)
    for row in candidates:
        vi = row["tgt"]
        if row["origin"] != "opus":
            continue
        longer = expand(vi, rng)
        if longer:
            add(spoken, longer, vi, "vi", "expanded")
        elif rng.random() < .025:
            add(spoken, vi, vi, "vi", "keep")

    def select(store):
        rows = list(store.values())
        rng.shuffle(rows)
        rows.sort(key=lambda r: (r["origin"] != "reviewed", r["origin"] not in ("reviewed", "parallel-variant")))
        return rows[:limit]

    return select(meaning), select(spoken)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--opus", type=Path, help="Local OPUS Moses parallel ZIP (no download)")
    p.add_argument("--src", choices=["zh", "en", "ja", "ko"], default="zh")
    p.add_argument("--reviewed", type=Path, help="Explicitly approved JSONL; optional spoken rendering per row")
    p.add_argument("--holdout", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True, help="New directory, never replaced")
    p.add_argument("--scan", type=int, default=200000)
    p.add_argument("--limit", type=int, default=6144)
    p.add_argument("--seed", type=int, default=42)
    args = p.parse_args()
    holdout = read_jsonl(args.holdout)
    if not holdout or min(args.limit, args.scan) <= 0 or not (args.opus or args.reviewed):
        p.error("Supply --opus or --reviewed, a nonempty holdout and positive sizes.")
    args.out.mkdir(parents=True, exist_ok=False)
    pairs = itertools.islice(read_pairs(args.opus, args.src), args.scan) if args.opus else ()
    sets = prepare(pairs, args.src, read_jsonl(args.reviewed) if args.reviewed else [], holdout, args.limit, args.seed)
    for name, rows in zip(("meaning", "spoken"), sets):
        with (args.out / (name + ".jsonl")).open("x", encoding="utf-8") as f:
            for row in rows:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        print(name, len(rows), dict(Counter(r["origin"] for r in rows)))


if __name__ == "__main__":
    main()
