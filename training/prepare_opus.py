"""Lọc corpus phụ đề song ngữ OPUS (định dạng Moses) thành JSONL {src, tgt} cho HP-4.

    python training/prepare_opus.py data/_opus/dl/vi-zh_CN.txt.zip --out data/corpus/opus_zh_vi.jsonl

Nguồn: OPUS OpenSubtitles v2024, cặp vi–zh_CN
(https://object.pouta.csc.fi/OPUS-OpenSubtitles/v2024/moses/vi-zh_CN.txt.zip, ~372 MB).
Phụ đề do cộng đồng gióng hàng tự động nên rất nhiều rác: dòng lệch nhau, dòng ghi
công nhóm dịch, câu tiếng Anh chưa dịch. Bộ lọc dưới đây giữ lại cặp câu thoại ngắn,
đúng chữ viết hai bên và có tỉ lệ độ dài hợp lý, rồi lấy mẫu ngẫu nhiên có hạt giống.

Chỉ dùng thư viện chuẩn + `backend.core.duration.syllables` (để đếm âm tiết đúng
như lúc tính token ngân sách).
"""

from __future__ import annotations

import argparse
import io
import json
import random
import re
import sys
import unicodedata
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.core.duration import syllables  # noqa: E402

_HAN = re.compile(r"[一-鿿]")
_KANA_HANGUL = re.compile(r"[぀-ヿ가-힯]")
_VI_MARK = re.compile(r"[ăâđêôơưàảãáạằẳẵắặầẩẫấậèẻẽéẹềểễếệìỉĩíịòỏõóọồổỗốộờởỡớợùủũúụừửữứựỳỷỹýỵ]", re.I)
_DIGITS = re.compile(r"\d+")
_LEAD = re.compile(r"^\s*(?:[-–—]+\s*)+")
_JUNK = re.compile(r"https?:|www\.|[<>{}\[\]♪#@|\\]|\.(?:com|net|org|vn)\b", re.I)
_CREDIT_ZH = re.compile(r"字幕|翻译|翻譯|校对|校對|时间轴|時間軸|压制|壓制|后期|後期|制作|製作|本集|片名|监制|導演|导演")
_CREDIT_VI = re.compile(r"phụ đề|subtitle|biên dịch|dịch bởi|subteam|sync|dịch:|translated", re.I)


def clean(text: str) -> str:
    # bỏ ký tự điều khiển hướng chữ vô hình (U+200E, U+202A…) mà phụ đề Netflix hay chèn đầu dòng
    text = "".join(ch for ch in unicodedata.normalize("NFC", text or "") if unicodedata.category(ch) != "Cf").strip()
    text = _LEAD.sub("", text)
    return re.sub(r"\s+", " ", text).strip()


def keep(zh: str, vi: str) -> bool:
    """Cặp câu có đáng tin để huấn luyện không."""
    if not zh or not vi or _JUNK.search(zh) or _JUNK.search(vi):
        return False
    if _CREDIT_ZH.search(zh) or _CREDIT_VI.search(vi):
        return False
    han = len(_HAN.findall(zh))
    if han < 2 or han > 40 or _KANA_HANGUL.search(zh):
        return False
    # câu nguồn phải chủ yếu là chữ Hán (cho phép dấu câu, vài chữ số)
    body = re.sub(r"[\s\W_]", "", zh)
    if not body or han / len(body) < 0.75:
        return False
    if _HAN.search(vi) or not _VI_MARK.search(vi):
        return False  # chưa dịch, hoặc là tiếng Anh
    n = syllables(vi)
    if n < 1 or n > 40 or len(vi) > 220:
        return False
    ratio = n / han
    if ratio < 0.55 or ratio > 2.6:
        return False  # tiếng Việt thường dài ~1,2–1,6 lần số chữ Hán; lệch xa là gióng hàng sai
    if sorted(_DIGITS.findall(zh)) != sorted(_DIGITS.findall(vi)):
        # chữ số Ả Rập bên này phải có ở bên kia (chữ số Hán thì không so được)
        if _DIGITS.search(zh):
            return False
    if vi.isupper() and n > 3:
        return False  # chữ in hoa cả câu: bảng hiệu, tiêu đề
    return True


def read_pairs(zip_path: Path):
    with zipfile.ZipFile(zip_path) as z:
        names = z.namelist()
        vi_name = next(n for n in names if n.endswith(".vi"))
        zh_name = next(n for n in names if n.lower().endswith((".zh_cn", ".zh")))
        with z.open(vi_name) as fv, z.open(zh_name) as fz:
            tv = io.TextIOWrapper(fv, encoding="utf-8", errors="replace", newline="\n")
            tz = io.TextIOWrapper(fz, encoding="utf-8", errors="replace", newline="\n")
            for vi, zh in zip(tv, tz):
                yield zh, vi


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("zip", type=Path, help="file .txt.zip tải từ OPUS (Moses)")
    ap.add_argument("--out", type=Path, default=ROOT / "data" / "corpus" / "opus_zh_vi.jsonl")
    ap.add_argument("--max", type=int, default=300_000, help="số cặp tối đa giữ lại (lấy mẫu ngẫu nhiên)")
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    rng = random.Random(args.seed)
    seen: set[int] = set()
    sample: list[tuple[str, str]] = []
    total = kept = 0
    for zh, vi in read_pairs(args.zip):
        total += 1
        zh, vi = clean(zh), clean(vi)
        if not keep(zh, vi):
            continue
        h = hash(zh)
        if h in seen:
            continue
        seen.add(h)
        kept += 1
        # lấy mẫu hồ chứa: mọi cặp đạt chuẩn có xác suất được chọn như nhau
        if len(sample) < args.max:
            sample.append((zh, vi))
        else:
            j = rng.randrange(kept)
            if j < args.max:
                sample[j] = (zh, vi)
        if total % 2_000_000 == 0:
            print(f"  đã đọc {total:,} dòng, đạt chuẩn {kept:,}", flush=True)

    rng.shuffle(sample)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", encoding="utf-8", newline="\n") as f:
        for zh, vi in sample:
            f.write(json.dumps({"src": zh, "tgt": vi, "src_lang": "zh", "tgt_lang": "vi"}, ensure_ascii=False) + "\n")
    print(f"Đọc {total:,} cặp, đạt chuẩn {kept:,} ({kept / max(1, total):.1%}), ghi {len(sample):,} -> {args.out}")


if __name__ == "__main__":
    main()
