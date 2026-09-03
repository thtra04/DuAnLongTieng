"""Sinh dữ liệu huấn luyện cho HP-3: chạy VieNeu-TTS trên từng câu, đo số giây.

    uv run python scripts/gen_duration_data.py --input scripts/seed_vi.txt \
        --output data/duration/samples.csv --limit 100

Mỗi dòng trong file đầu vào là một câu tiếng Việt. Kết quả là CSV với các cột
text, voice, style, seconds — chính là bộ ba (văn bản, giọng, thời lượng đo
thật) mà đề cương mô tả. Chạy lại thì bỏ qua câu đã đo, nên ngắt giữa chừng
không mất gì.

Số giây là độ dài clip SAU khi cắt lặng đầu/cuối, đúng như lúc lồng tiếng
thật (`dubbing.build_dub_track` cũng cắt như vậy trước khi ghép).
"""

from __future__ import annotations

import argparse
import csv
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import dubbing  # noqa: E402


def read_sentences(path: Path) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        s = " ".join(line.split())
        if s and not s.startswith("#") and s not in seen:
            seen.add(s)
            out.append(s)
    return out


def already_done(path: Path) -> set[tuple[str, str, str]]:
    if not path.exists():
        return set()
    with path.open(encoding="utf-8", newline="") as fh:
        return {(r["text"], r["voice"], r["style"]) for r in csv.DictReader(fh)}


def main() -> int:
    ap = argparse.ArgumentParser(description="Sinh dữ liệu thời lượng đọc bằng VieNeu-TTS")
    ap.add_argument("--input", required=True, type=Path, help="file câu, mỗi dòng một câu")
    ap.add_argument("--output", default=ROOT / "data" / "duration" / "samples.csv", type=Path)
    ap.add_argument("--voice", default="", help="id giọng dựng sẵn (trống = mặc định của engine)")
    ap.add_argument("--style", default="tu_nhien")
    ap.add_argument("--limit", type=int, default=0, help="chỉ đo N câu đầu (0 = tất cả)")
    args = ap.parse_args()

    sentences = read_sentences(args.input)
    if args.limit:
        sentences = sentences[: args.limit]
    done = already_done(args.output)
    todo = [s for s in sentences if (s, args.voice, args.style) not in done]
    print(f"{len(sentences)} câu, {len(done)} đã đo, còn {len(todo)}.")
    if not todo:
        return 0

    ok, why = dubbing.available(deep=True)
    if not ok:
        print("Không chạy được TTS:", why)
        return 1
    engine = dubbing.get_engine()
    if not args.voice:
        voices = dubbing.list_voices()
        args.voice = voices[0]["id"] if voices else ""
        print("Giọng:", args.voice or "(mặc định)")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    new_file = not args.output.exists()
    t0 = time.time()
    with args.output.open("a", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        if new_file:
            writer.writerow(["text", "voice", "style", "seconds"])
        for i, text in enumerate(todo, 1):
            try:
                import numpy as np

                kwargs = {"style": args.style}
                if args.voice:
                    kwargs["voice"] = args.voice
                audio = np.asarray(engine.infer(text, **kwargs), dtype=np.float32).reshape(-1)
                audio, _ = dubbing._trim_silence(audio)
                seconds = audio.size / dubbing.SR
            except Exception as exc:
                print(f"  [{i}/{len(todo)}] lỗi, bỏ qua: {exc}")
                continue
            if dubbing._runaway(seconds, text):
                print(f"  [{i}/{len(todo)}] TTS sinh chạy loạn ({seconds:.1f}s), bỏ qua: {text[:40]}")
                continue
            writer.writerow([text, args.voice, args.style, f"{seconds:.3f}"])
            fh.flush()
            if i % 10 == 0 or i == len(todo):
                rate = (time.time() - t0) / i
                print(f"  [{i}/{len(todo)}] {seconds:5.2f}s  ·  ~{rate:.1f}s/câu, còn ~{rate * (len(todo) - i) / 60:.0f} phút")
    print("Xong ->", args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
