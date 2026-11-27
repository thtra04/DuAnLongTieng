"""Paired, offline comparison against the installed MT adapter and script shortener."""
from __future__ import annotations

import argparse
import gc
import itertools
import json
import os
import random
import re
from pathlib import Path

from sacrebleu import corpus_chrf

from backend.core import budget, duration, shorten, translate
from training.prepare_dialogue import key, read_jsonl, terms
from training.prepare_opus import clean, keep_lang, read_pairs


def unseen_opus(archive, excludes, probes, lang, count, seed):
    probe_keys = set().union(*(terms(r) for r in probes))
    blocked = set(probe_keys)
    for path in excludes:
        with path.open(encoding="utf-8-sig") as f:
            for line in f:
                if line.strip():
                    keys = terms(json.loads(line))
                    if keys & probe_keys:
                        raise ValueError(f"The dialogue holdout overlaps {path.name}; use a fresh holdout.")
                    blocked.update(keys)
    rows = []
    for x, y in itertools.islice(read_pairs(archive, lang), 600000, 700000):
        src, tgt = clean(x), clean(y)
        if not keep_lang(src, tgt, lang):
            continue
        keys = {key(src), key(tgt)}
        if not (keys & blocked):
            rows.append({"src": src, "tgt": tgt})
            blocked.update(keys)
            if len(rows) == 10 * count:
                break
    if len(rows) < count:
        raise ValueError("Not enough disjoint parallel examples for the requested sample.")
    return random.Random(seed).sample(rows, count)


def score_mt(rows, outputs):
    numbered = [(r, o) for r, o in zip(rows, outputs) if re.search(r"\d", r["src"])]
    checks = [any(re.search(r"(?<!\w)" + re.escape(alt) + r"(?!\w)", out.casefold()) for alt in alternatives)
              for r, out in zip(rows, outputs) for alternatives in r.get("checks", [])]
    return {"n": len(rows), "chrf": round(corpus_chrf(outputs, [[r["tgt"] for r in rows]]).score, 2),
            "numbers_correct": sum(re.findall(r"\d+", r["src"]) == re.findall(r"\d+", o) for r, o in numbered),
            "numbered": len(numbered), "lexical_matched": sum(checks), "lexical_total": len(checks)}


def score_spoken(rows, outputs):
    return {"n": len(rows), "chrf": round(corpus_chrf(outputs, [[r["spoken"] for r in rows]]).score, 2),
            "fits": sum(duration.syllables(o) <= r["cap"] for r, o in zip(rows, outputs)),
            "changed": sum(o != r["tgt"] for r, o in zip(rows, outputs)),
            "anchor_mismatch": sum(not budget.keeps_anchors(r["tgt"], o) for r, o in zip(rows, outputs))}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--src", default="zh")
    p.add_argument("--meaning", required=True, type=Path)
    p.add_argument("--spoken", required=True, type=Path)
    p.add_argument("--holdout", required=True, type=Path, help="Original src / approved tgt / spoken reference / syllable cap")
    p.add_argument("--opus", type=Path, help="Optional additional held-out test from the local parallel archive")
    p.add_argument("--exclude", type=Path, action="append", default=[], help="Exclude each training corpus, including warm start")
    p.add_argument("--sample", default=192, type=int)
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args()
    if args.out.exists() or (args.opus and (not args.exclude or args.sample <= 0)):
        p.error("Use a new report path and exclude training corpora when sampling parallel data.")
    probes = read_jsonl(args.holdout)
    if not probes or any(not all(r.get(k) for k in ("src", "tgt", "spoken"))
                         or type(r.get("cap")) is not int or r["cap"] <= 0 for r in probes):
        p.error("Each holdout cue needs a source, subtitle, spoken reference and positive cap.")
    other = unseen_opus(args.opus, args.exclude, probes, args.src, args.sample, 42) if args.opus else []
    rows = probes + other
    texts = [r["src"] for r in rows]
    expected = ["meaning_" + args.src, "spoken_vi"]
    report = {"src": args.src, "holdout": args.holdout.name, "mt": {}, "spoken": {}}
    examples = [dict(r) for r in probes]

    os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", VSUB_NLLB_LORA="1")
    for variant in ("current", "candidate"):
        for name, path in (("VSUB_MEANING_ADAPTER", args.meaning), ("VSUB_SPOKEN_ADAPTER", args.spoken)):
            if variant == "current":
                os.environ.pop(name, None)
            else:
                os.environ[name] = str(path.resolve())
        translate._nllb_cache.clear()
        gc.collect()
        loaded = translate._load_nllb()[3]
        if variant == "current":
            baseline = translate.lora_for(args.src, "vi")
            required = [baseline] if baseline else []
            report["baseline"] = baseline or "nllb_base"
        else:
            required = expected
        if not set(required).issubset(loaded):
            raise RuntimeError(f"{variant}: expected {required}, actually loaded {loaded}")
        outputs = translate._translate_nllb(texts, args.src, "vi")
        report["mt"][variant] = {"dialogue": score_mt(probes, outputs[:len(probes)])}
        if other:
            report["mt"][variant]["parallel"] = score_mt(other, outputs[len(probes):])
        for row, out in zip(examples, outputs):
            row[variant] = out
        print(variant, report["mt"][variant], flush=True)

    requests = [{"text": r["tgt"], "target_syllables": r["cap"]} for r in probes]
    before = [r["tgt"] for r in probes]
    raw = translate._translate_nllb(before, "vi", "vi", budgets=[r["cap"] for r in probes], spoken=True)
    for name, outputs in (("unchanged", before), ("rules", shorten.make_tightener()(requests)),
                          ("model_raw", raw), ("rules_plus_model", translate.spoken_tightener()(requests))):
        if name in ("rules", "rules_plus_model"):
            outputs = [budget._shorter_line(b, o) for b, o in zip(before, outputs)]
        report["spoken"][name] = score_spoken(probes, outputs)
        for row, out in zip(examples, outputs):
            row[name] = out
    print("spoken", report["spoken"], flush=True)
    # Only the explicitly supplied review probes are saved, not sampled OPUS subtitles.
    report["examples"] = examples
    with args.out.open("x", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
