"""Dựng corpus song ngữ cho notebook 03 (LoRA NLLB) từ dữ liệu của chính tool.

    uv run python training/build_corpus.py            # ghi data/corpus/vidub_train.jsonl
    uv run python training/build_corpus.py --holdout data/_bench/gold/gold.json

Ba nguồn, xếp theo độ tin cậy:

    1. Bộ nhớ dịch — câu người dùng đã sửa tay và duyệt lúc xuất (origin "user").
    2. Dự án cũ dịch bằng engine AI (Claude / OpenAI) — chưng cất tri thức: mô hình
       nhỏ chạy offline học theo bản dịch của mô hình lớn (origin "ai").
    3. File JSONL ngoài truyền qua --extra, ví dụ phụ đề OpenSubtitles đã lọc (origin "extra").

Bản dịch Google trong dự án cũ KHÔNG được lấy: đo trên bộ gold nó chỉ đúng ~73 % câu,
học theo nó là học luôn cái sai.

`--holdout` nhận file gold (danh sách {"text": ...}): câu nguồn nào có trong đó bị loại
khỏi corpus, để tập kiểm thử không rò vào tập huấn luyện.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

AI_ENGINES = ("claude", "openai")


def from_jobs(job_dir: Path) -> list[dict]:
    """Cặp câu từ các dự án dịch bằng engine AI, ghép lại theo câu như lúc dịch."""
    from backend.core.subtitles import Cue
    from backend.core.translate import _join_fragments, group_cues

    rows = []
    for path in sorted(Path(job_dir).glob("*/state.json")):
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if (state.get("cfg") or {}).get("engine") not in AI_ENGINES:
            continue
        cues = [Cue.from_dict(c) for c in state.get("cues") or []]
        for g in group_cues(cues, split_cjk_lines=True):
            src = _join_fragments([cues[i].text for i in g]).strip()
            tgt = _join_fragments([cues[i].text2 for i in g]).strip()
            if src and tgt:
                rows.append({"src": src, "tgt": tgt, "src_lang": state.get("source_lang") or "",
                             "tgt_lang": state.get("target_lang") or "", "origin": "ai"})
    return rows


def from_memory() -> list[dict]:
    import tempfile

    from backend.store import memory

    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "tm.jsonl"
        memory.export_jsonl(out)
        rows = [json.loads(ln) for ln in out.read_text(encoding="utf-8").splitlines() if ln.strip()]
    return [dict(r, origin="user") for r in rows]


def from_file(path: Path) -> list[dict]:
    rows = []
    for ln in Path(path).read_text(encoding="utf-8").splitlines():
        if ln.strip():
            r = json.loads(ln)
            if r.get("src") and r.get("tgt"):
                rows.append({"src": r["src"], "tgt": r["tgt"], "src_lang": r.get("src_lang", ""),
                             "tgt_lang": r.get("tgt_lang", ""), "origin": "extra"})
    return rows


def _letters(text: str) -> str:
    return re.sub(r"[\W_]+", "", text or "").lower()


def _bigrams(text: str) -> set[str]:
    t = _letters(text)
    return {t[i:i + 2] for i in range(len(t) - 1)}


def near_holdout(src: str, held_grams: set[str], threshold: float = 0.5) -> bool:
    """Câu này có phải là cùng lời thoại với tập kiểm thử, chỉ khác cách cắt câu / lỗi ASR?

    Dự án cũ của chính tool có thể là đúng video dùng làm tập kiểm thử: cùng lời thoại
    nhưng ghép cue khác đi ("一个人走夜路" + "不怕遇见歹人" thành một câu) hoặc ASR nghe
    lệch một chữ, nên so khớp nguyên câu không bắt được — đo thật có 172 cặp lọt kiểu này.
    Ở đây so theo cặp chữ liền nhau: quá nửa số cặp chữ của câu nằm trong tập kiểm thử
    thì coi là rò.
    """
    grams = _bigrams(src)
    if not grams or not held_grams:
        return False
    return len(grams & held_grams) / len(grams) >= threshold


def merge(sources: list[list[dict]], holdout: set[str] | None = None) -> tuple[list[dict], dict]:
    """Gộp các nguồn; nguồn đứng trước thắng khi trùng câu gốc. Trả về (corpus, thống kê).

    Tập kiểm thử bị loại hai mức: trùng nguyên câu với mọi nguồn; riêng dữ liệu của
    chính tool (bộ nhớ dịch, dự án cũ) còn bị loại khi "gần trùng" (`near_holdout`).
    Corpus ngoài (`extra`) không áp mức hai, kẻo mất oan các câu ngắn phổ biến.
    """
    from backend.store.memory import normalize

    held = {normalize(t) for t in (holdout or set())}
    held_grams = set().union(*[_bigrams(t) for t in held]) if held else set()
    seen: set[tuple[str, str]] = set()
    out: list[dict] = []
    stats = {"total": 0, "duplicate": 0, "holdout": 0, "by_origin": {}}
    for rows in sources:
        for r in rows:
            stats["total"] += 1
            key = (normalize(r["src"]), (r.get("tgt_lang") or "").lower())
            if key[0] in held or (r.get("origin") != "extra" and near_holdout(r["src"], held_grams)):
                stats["holdout"] += 1
                continue
            if not key[0] or key in seen or normalize(r["src"]) == normalize(r["tgt"]):
                stats["duplicate"] += 1
                continue
            seen.add(key)
            out.append(r)
            stats["by_origin"][r["origin"]] = stats["by_origin"].get(r["origin"], 0) + 1
    return out, stats


def main() -> None:
    from backend.config import DATA_DIR, JOB_DIR

    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", type=Path, default=DATA_DIR / "corpus" / "vidub_train.jsonl")
    ap.add_argument("--extra", type=Path, action="append", default=[], help="JSONL {src, tgt} bổ sung")
    ap.add_argument("--holdout", type=Path, help="file gold JSON; câu nguồn trong đó bị loại")
    args = ap.parse_args()

    holdout = set()
    if args.holdout:
        holdout = {str(g.get("text") or g.get("zh") or "") for g in json.loads(args.holdout.read_text(encoding="utf-8"))}
    corpus, stats = merge([from_memory(), from_jobs(JOB_DIR), *[from_file(p) for p in args.extra]], holdout)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", encoding="utf-8", newline="\n") as f:
        for r in corpus:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"{len(corpus)} cặp câu -> {args.out}")
    print(f"  theo nguồn: {stats['by_origin']}; bỏ {stats['duplicate']} trùng, {stats['holdout']} thuộc tập kiểm thử")
    if len(corpus) < 5000:
        print("  ⚠ Dưới 5.000 cặp: chưa đủ để LoRA học được gì đáng kể — thêm corpus ngoài bằng --extra.")


if __name__ == "__main__":
    main()
