"""Lọc corpus phụ đề song ngữ OPUS (định dạng Moses) thành JSONL {src, tgt} cho HP-4.

    python training/prepare_opus.py data/_opus/dl/vi-zh_CN.txt.zip --out data/corpus/opus_zh_vi.jsonl
    python training/prepare_opus.py data/_opus/dl/ko-vi.txt.zip      # → data/corpus/opus_ko_vi.jsonl (cũng: ja-vi, en-vi)

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


# ------------------------------------------------ ngôn ngữ nguồn khác (20/11/2026)
# Cùng ý như bộ lọc tiếng Trung ở trên (giữ nguyên để kết quả Trung → Việt dựng lại được):
# câu nguồn đúng chữ viết, độ dài vừa phải, tỉ lệ "âm tiết Việt / đơn vị nguồn" hợp lý.
# Đơn vị nguồn: Hàn = khối chữ Hangul (≈ một âm tiết), Nhật = ký tự kana + kanji, Anh = từ.
_HANGUL = re.compile(r"[가-힯]")
_KANA = re.compile(r"[぀-ヿ]")
_JA_CHAR = re.compile(r"[぀-ヿ一-鿿]")
_EN_WORD = re.compile(r"[A-Za-z]+(?:'[A-Za-z]+)?")
_CREDIT_SRC = {
    "ko": re.compile(r"자막|번역|싱크|제작|감독"),
    "ja": re.compile(r"字幕|翻訳|製作|監督|制作"),
    "en": re.compile(r"subtitle|translat|synced|corrected by|opensubtitles|captioning", re.I),
}
# (đơn vị tối thiểu, tối đa, tỉ lệ âm tiết Việt / đơn vị: thấp, cao, tỉ lệ đơn vị trong phần chữ tối thiểu)
_LIMITS = {"ko": (2, 40, 0.45, 2.6, 0.7), "ja": (2, 60, 0.25, 1.6, 0.75), "en": (1, 30, 0.6, 2.8, 0.0)}


def units(src: str, lang: str) -> int:
    if lang == "ko":
        return len(_HANGUL.findall(src))
    if lang == "ja":
        return len(_JA_CHAR.findall(src))
    return len(_EN_WORD.findall(src))


def keep_lang(src: str, vi: str, lang: str) -> bool:
    """Bộ lọc cho Hàn / Nhật / Anh → Việt."""
    if lang == "zh":
        return keep(src, vi)
    if not src or not vi or _JUNK.search(src) or _JUNK.search(vi):
        return False
    if _CREDIT_SRC[lang].search(src) or _CREDIT_VI.search(vi):
        return False
    lo, hi, rlo, rhi, share = _LIMITS[lang]
    u = units(src, lang)
    if u < lo or u > hi:
        return False
    body = re.sub(r"[\s\W_\d]", "", src)
    if not body:
        return False
    if lang == "ko" and (u / len(body) < share or _KANA.search(src)):
        return False
    if lang == "ja" and (u / len(body) < share or not _KANA.search(src) or _HANGUL.search(src)):
        return False  # không có kana thì dễ là câu tiếng Trung lẫn vào
    if lang == "en" and (not body.isascii() or _VI_MARK.search(src)):
        return False
    if _HANGUL.search(vi) or _JA_CHAR.search(vi) or not _VI_MARK.search(vi):
        return False  # bên Việt chưa dịch, hoặc là tiếng Anh
    if lang == "en" and vi.lower() == src.lower():
        return False
    n = syllables(vi)
    if n < 1 or n > 40 or len(vi) > 220:
        return False
    if not rlo <= n / u <= rhi:
        return False
    if _DIGITS.search(src) and sorted(_DIGITS.findall(src)) != sorted(_DIGITS.findall(vi)):
        return False
    if vi.isupper() and n > 3:
        return False
    return True


def detect_lang(zip_path: Path) -> str:
    name = zip_path.name.lower()
    for lang in ("ko", "ja", "en", "zh"):
        if f"{lang}-" in name or f"-{lang}" in name:
            return lang
    raise SystemExit(f"Không đoán được ngôn ngữ nguồn từ tên tệp {zip_path.name}; dùng --src")


def read_pairs(zip_path: Path, lang: str = "zh"):
    with zipfile.ZipFile(zip_path) as z:
        names = z.namelist()
        vi_name = next(n for n in names if n.endswith(".vi"))
        ends = (".zh_cn", ".zh") if lang == "zh" else (f".{lang}",)
        zh_name = next(n for n in names if n.lower().endswith(ends))
        with z.open(vi_name) as fv, z.open(zh_name) as fz:
            tv = io.TextIOWrapper(fv, encoding="utf-8", errors="replace", newline="\n")
            tz = io.TextIOWrapper(fz, encoding="utf-8", errors="replace", newline="\n")
            for vi, zh in zip(tv, tz):
                yield zh, vi


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("zip", type=Path, help="file .txt.zip tải từ OPUS (Moses)")
    ap.add_argument("--src", choices=["zh", "ko", "ja", "en"], help="ngôn ngữ nguồn (mặc định đoán từ tên tệp)")
    ap.add_argument("--out", type=Path, help="mặc định data/corpus/opus_<src>_vi.jsonl")
    ap.add_argument("--max", type=int, default=300_000, help="số cặp tối đa giữ lại (lấy mẫu ngẫu nhiên)")
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()
    lang = args.src or detect_lang(args.zip)
    args.out = args.out or ROOT / "data" / "corpus" / f"opus_{lang}_vi.jsonl"

    rng = random.Random(args.seed)
    seen: set[int] = set()
    sample: list[tuple[str, str]] = []
    total = kept = 0
    for zh, vi in read_pairs(args.zip, lang):
        total += 1
        zh, vi = clean(zh), clean(vi)
        if not keep_lang(zh, vi, lang):
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
            f.write(json.dumps({"src": zh, "tgt": vi, "src_lang": lang, "tgt_lang": "vi"}, ensure_ascii=False) + "\n")
    print(f"Đọc {total:,} cặp, đạt chuẩn {kept:,} ({kept / max(1, total):.1%}), ghi {len(sample):,} -> {args.out}")


if __name__ == "__main__":
    main()
