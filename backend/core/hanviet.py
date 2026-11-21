"""Âm Hán Việt cho bản dịch Trung → Việt: tự học thuật ngữ, cài sẵn vào câu gốc, sửa phiên âm sót.

Google và NLLB hay để tên riêng, cách xưng hô cổ trang ở dạng pinyin hoặc dịch sát chữ
(đo trên bộ gold: 郎君 → "Lang Jun", 霍 → "Huo", 春风楼 → "tháp Chunfeng", 奴家 → "gia đình
nô lệ"). Module này làm ba việc, không cần mạng hay mô hình:

1. `harvest(zh, vi)` — trong một bản dịch đã duyệt, tìm những cụm chữ Hán được đọc theo âm
   Hán Việt (郎君 → "lang quân", 霍 → "Hoắc"). Tra âm từng chữ trong `hanviet_data.tsv`.
2. Bộ thuật ngữ tự học (`data/hanviet_learned.json`): `learn()` ghi các cụm học được từ câu
   người dùng sửa tay (chỉ phần họ sửa), từ bộ thuật ngữ đã gõ ở các dự án, và tên riêng
   lặp lại trong bản dịch AI. Lúc dịch bằng Google/NLLB, `learned_pairs()` trả về các cụm có
   mặt trong kịch bản để cài sẵn vào câu gốc như bộ thuật ngữ.
3. `fix_pinyin(zh, vi)` — sau khi dịch, đoạn phiên âm còn sót ("Lang Jun", "Chunfeng") được
   đổi sang âm Hán Việt của ĐÚNG các chữ trong câu gốc có pinyin đó ("Lang Quân", "Xuân Phong").
   Chỉ sửa khi khớp được với câu gốc, nên từ tiếng Việt trùng mặt chữ pinyin (an, ba, lang)
   không bị đụng tới.

Tắt hẳn bằng biến môi trường VSUB_HANVIET=0.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
import unicodedata
from functools import lru_cache
from pathlib import Path

DATA = Path(__file__).with_name("hanviet_data.tsv")
LEARNED_FILE = "hanviet_learned.json"
_HAN = re.compile(r"[㐀-䶿一-鿿豈-﫿]+")
_WORD = re.compile(r"[^\W\d_]+", re.UNICODE)
_SENT_END = re.compile(r"[.!?…:;\"“”«»()\[\]\-–—]\s*$")
# thứ tự ưu tiên khi cùng một cụm học được nhiều cách dịch
ORIGINS = {"sửa tay": 3, "thuật ngữ": 2, "AI": 1}
# hư từ / đại từ rất thường gặp: một mình thì không bao giờ là tên riêng (了 "liễu" trùng họ 柳 "Liễu")
_FUNCTION = set("了的是不我你他她它在有这那就也都和吗呢吧啊么着过给让被把从对说要会能去来上下个一们之其而以与及或但却又还很太更最已得地")
_lock = threading.Lock()


def enabled(source: str | None, target: str | None) -> bool:
    src, tgt = (source or "").lower(), (target or "").lower()
    return os.environ.get("VSUB_HANVIET", "1") != "0" and src.startswith(("zh", "yue")) and tgt.startswith("vi")


# ------------------------------------------------------------------ bảng âm từng chữ

@lru_cache(maxsize=1)
def _table() -> tuple[dict[str, tuple[str, dict[str, list[str]]]], frozenset[str], frozenset[str]]:
    """(chữ → (âm thường dùng, {pinyin: [âm…]}), âm pinyin trùng từ tiếng Việt, mọi âm pinyin)."""
    table: dict[str, tuple[str, dict[str, list[str]]]] = {}
    viet: frozenset[str] = frozenset()
    for ln in DATA.read_text(encoding="utf-8").splitlines():
        if ln.startswith("#viet\t"):
            viet = frozenset(ln.split("\t", 1)[1].split(","))
            continue
        if not ln or ln.startswith("#"):
            continue
        ch, default, rest = ln.split("\t")
        table[ch] = (default, {p: hv.split("/") for p, hv in (x.split("=", 1) for x in rest.split(";"))})
    syllables = frozenset(p for _d, m in table.values() for p in m if p.isalpha())
    return table, viet, syllables


def readings(ch: str) -> list[str]:
    """Mọi âm Hán Việt của một chữ, âm thường dùng trước."""
    entry = _table()[0].get(ch)
    if not entry:
        return []
    out = [entry[0]]
    for hv in entry[1].values():
        out += [h for h in hv if h not in out]
    return out


def reading(text: str, pinyins: list[str] | None = None) -> str | None:
    """Âm Hán Việt của một chuỗi chữ Hán ("郎君" → "lang quân"); `pinyins` (mỗi chữ một âm)
    chọn đúng âm cho chữ nhiều âm. None nếu có chữ chưa có trong bảng."""
    table = _table()[0]
    out = []
    for i, ch in enumerate(text):
        entry = table.get(ch)
        if not entry:
            return None
        hv = entry[1].get(pinyins[i]) if pinyins and i < len(pinyins) else None
        out.append(hv[0] if hv else entry[0])
    return " ".join(out)


def canon(word: str) -> str:
    """Khoá so âm tiết tiếng Việt: chữ thường, dấu thanh tách riêng (thuỷ = thủy, hoà = hòa)."""
    s = unicodedata.normalize("NFD", (word or "").lower())
    tones = "".join(ch for ch in s if ch in "̣̀́̃̉")
    base = unicodedata.normalize("NFC", "".join(ch for ch in s if ch not in "̣̀́̃̉"))
    return base + tones


@lru_cache(maxsize=20000)
def _cands(ch: str) -> frozenset[str]:
    return frozenset(canon(h) for h in readings(ch))


def _words(vi: str) -> list[re.Match]:
    return list(_WORD.finditer(unicodedata.normalize("NFC", vi or "")))


def _starts_sentence(vi: str, pos: int) -> bool:
    before = vi[:pos].rstrip()
    return not before or bool(_SENT_END.search(before))


# ------------------------------------------------------------------ 1. tìm cụm Hán Việt

def harvest(zh: str, vi: str, max_len: int = 4, names: set[str] | None = None) -> list[tuple[str, str]]:
    """Cặp (cụm chữ Hán, cách viết trong bản dịch) mà bản dịch đọc đúng theo âm Hán Việt.

    Cụm từ hai chữ trở lên thì nhận luôn (trùng ngẫu nhiên hai âm liền nhau là rất hiếm);
    cụm một chữ chỉ nhận khi bản dịch viết hoa giữa câu — tức là tên riêng (霍 → "Hoắc").
    Cụm dài được tìm trước; chữ / từ đã khớp thì không khớp lần nữa. Cụm đứng đầu câu thì
    không biết chữ hoa là do tên riêng hay do đầu câu: viết thường, trừ khi chữ đầu của cụm
    nằm trong `names` (chữ đã biết là tên riêng, ví dụ 霍 trong "霍儿 → Hoắc nhi").
    """
    vi = unicodedata.normalize("NFC", vi or "")
    words = _words(vi)
    low = [canon(m.group()) for m in words]
    taken: set[int] = set()
    found: list[tuple[str, str]] = []
    for run in _HAN.findall(unicodedata.normalize("NFC", zh or "")):
        covered = [False] * len(run)
        for size in range(min(max_len, len(run)), 0, -1):
            for s in range(len(run) - size + 1):
                if any(covered[s:s + size]) or (size == 1 and run[s] in _FUNCTION):
                    continue
                cands = [_cands(ch) for ch in run[s:s + size]]
                if not all(cands):
                    continue
                for k in range(len(low) - size + 1):
                    if any(k + j in taken for j in range(size)):
                        continue
                    if not all(low[k + j] in cands[j] for j in range(size)):
                        continue
                    first = words[k]
                    if size == 1 and not (first.group()[:1].isupper() and not _starts_sentence(vi, first.start())):
                        continue
                    term = vi[first.start(): words[k + size - 1].end()]
                    if size > 1 and not term.replace(" ", "").isalpha():
                        continue  # hai âm vắt qua dấu câu ("… gia, đình") không phải một cụm
                    sub = run[s:s + size]
                    found.append((sub, _case(vi, words, k, size, term, sub[0] in (names or ()))))
                    covered[s:s + size] = [True] * size
                    taken.update(range(k, k + size))
                    break
    return found


def _case(vi: str, words: list[re.Match], k: int, size: int, term: str, known_name: bool) -> str:
    """Giữ hoa/thường như bản dịch, trừ chữ hoa chỉ vì đứng đầu câu ("Lang quân sợ gì" → "lang quân")."""
    if known_name or not _starts_sentence(vi, words[k].start()):
        return term
    if any(w.group()[:1].isupper() for w in words[k + 1:k + size]):
        return term
    return term[:1].lower() + term[1:]


def harvest_many(pairs: list[tuple[str, str]]) -> dict[tuple[str, str], int]:
    """`harvest` trên cả kịch bản, hai lượt: lượt đầu tìm chữ nào là tên riêng (viết hoa giữa
    câu), lượt sau dùng nó để quyết hoa/thường cho cụm đứng đầu câu. Trả về {(cụm, cách viết): số câu}."""
    names = {z[0] for zh, vi in pairs for z, v in harvest(zh, vi) if v[:1].isupper()}
    names |= {zh[0] for zh, t in load().items() if t["vi"][:1].isupper()}
    out: dict[tuple[str, str], int] = {}
    for zh, vi in pairs:
        for p in set(harvest(zh, vi, names=names)):
            out[p] = out.get(p, 0) + 1
    return out


def contains(text: str, term: str) -> bool:
    """`term` (một hay nhiều âm tiết) có nằm liền nhau trong `text` không — không phân biệt hoa/thường,
    không phân biệt kiểu bỏ dấu (thuỷ = thủy)."""
    words = [canon(m.group()) for m in _words(text)]
    want = [canon(m.group()) for m in _words(term)]
    n = len(want)
    return n > 0 and any(words[i:i + n] == want for i in range(len(words) - n + 1))


def is_han(text: str) -> bool:
    return bool(_HAN.fullmatch((text or "").strip()))


def corrections(zh: str, before: str, after: str) -> list[tuple[str, str]]:
    """Cụm Hán Việt có trong bản người dùng sửa (`after`) mà bản máy dịch (`before`) không có."""
    names = {z[0] for z, t in load().items() if t["vi"][:1].isupper()}
    return [(z, v) for z, v in harvest(zh, after, names=names) if not contains(before, v)]


# ------------------------------------------------------------------ 2. bộ thuật ngữ tự học

LEARNED_PATH: Path | None = None  # test đặt sang chỗ tạm; None = data/hanviet_learned.json


def _path() -> Path:
    from ..config import DATA_DIR

    return LEARNED_PATH or Path(DATA_DIR) / LEARNED_FILE


def load() -> dict[str, dict]:
    try:
        return json.loads(_path().read_text(encoding="utf-8")).get("terms", {})
    except (OSError, ValueError):
        return {}


def learn(pairs: list[tuple[str, str]], origin: str) -> int:
    """Ghi các cụm học được. Cụm đã có thì cộng số lần gặp; nguồn ưu tiên cao hơn (sửa tay >
    thuật ngữ > AI) được đổi cách dịch. Trả về số cụm mới hoặc đổi cách dịch."""
    pairs = [(z.strip(), v.strip()) for z, v in pairs if z and v and _HAN.fullmatch(z.strip()) and v.strip()]
    if not pairs:
        return 0
    changed = 0
    with _lock:
        terms = load()
        now = time.time()
        for zh, vi in pairs:
            t = terms.get(zh)
            if t is None:
                terms[zh] = {"vi": vi, "origin": origin, "n": {origin: 1}, "updated": now}
                changed += 1
                continue
            t["n"][origin] = t["n"].get(origin, 0) + 1
            if ORIGINS.get(origin, 0) >= ORIGINS.get(t["origin"], 0) and t["vi"] != vi:
                t.update(vi=vi, origin=origin)
                changed += 1
            t["updated"] = now
        path = _path()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"terms": terms}, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, path)
    return changed


def usable(zh: str, t: dict) -> bool:
    """Cụm nào được tự cài vào câu gốc: chữ một chữ thì phải là tên riêng (viết hoa); học từ
    AI thì phải gặp từ hai lần trở lên."""
    if len(zh) < 2 and not t["vi"][:1].isupper():
        return False
    return t["origin"] != "AI" or sum(t["n"].values()) >= 2


def learned_pairs(texts: list[str], exclude: set[str] | None = None) -> list[tuple[str, str]]:
    """Các cụm đã học có mặt trong kịch bản, dài trước (để 霍姑娘 được thay trước 霍)."""
    exclude = exclude or set()
    script = "\n".join(texts)
    pairs = [(zh, t["vi"]) for zh, t in load().items()
             if zh not in exclude and zh in script and usable(zh, t)]
    return sorted(pairs, key=lambda p: -len(p[0]))


def learn_names(texts: list[str], outs: list[str]) -> int:
    """Từ bản dịch AI: chỉ học tên riêng (viết hoa) gặp từ hai câu trở lên trong cùng kịch bản."""
    seen = harvest_many(list(zip(texts, outs)))
    return learn([p for p, n in seen.items() if n >= 2 and p[1][:1].isupper()], "AI")


# ------------------------------------------------------------------ 3. sửa phiên âm sót


@lru_cache(maxsize=4096)
def _split_pinyin(token: str) -> tuple[str, ...] | None:
    """'dasheng' → ('da', 'sheng'); không tách được hết thành âm pinyin thì None."""
    syl = _table()[2]
    t = unicodedata.normalize("NFD", token.lower())
    t = "".join(ch for ch in t if unicodedata.category(ch) != "Mn").replace("ü", "u").replace("v", "u")
    if not t.isascii() or not t.isalpha():
        return None
    best: list[tuple[str, ...] | None] = [None] * (len(t) + 1)
    best[0] = ()
    for i in range(1, len(t) + 1):
        for j in range(max(0, i - 6), i):
            if best[j] is not None and t[j:i] in syl:
                cand = best[j] + (t[j:i],)
                if best[i] is None or len(cand) < len(best[i]):
                    best[i] = cand
    return best[len(t)]


def _pinyin_runs(vi: str) -> list[tuple[int, int, tuple[str, ...]]]:
    """Các đoạn liền nhau gồm từ viết hoa, không dấu tiếng Việt, tách được thành pinyin."""
    runs, cur = [], []
    for m in _WORD.finditer(vi):  # cả từ (kể cả chữ có dấu tiếng Việt), chỉ từ ASCII mới có thể là pinyin
        parts = _split_pinyin(m.group()) if m.group()[:1].isupper() and m.group().isascii() else None
        if parts and cur and vi[cur[-1][1]: m.start()].strip() == "":
            cur.append((m.start(), m.end(), parts))
            continue
        if cur:
            runs.append(cur)
        cur = [(m.start(), m.end(), parts)] if parts else []
    if cur:
        runs.append(cur)
    return [(r[0][0], r[-1][1], tuple(p for _s, _e, ps in r for p in ps)) for r in runs]


def fix_pinyin(zh: str, vi: str, learned: dict[str, str] | None = None) -> tuple[str, list[tuple[str, str]]]:
    """Đổi phiên âm pinyin còn sót trong bản dịch sang âm Hán Việt của đúng chữ trong câu gốc.

    Chỉ sửa một đoạn khi (1) khớp được với một dãy chữ liền nhau trong câu gốc có đúng các âm
    pinyin đó, và (2) đoạn có ít nhất một âm không phải âm tiết tiếng Việt (Jun, Huo, Zhu…) hoặc
    gồm từ hai âm trở lên đứng giữa câu. Cụm đã học (`learned`: chữ Hán → cách viết) thì viết
    đúng như đã học ("lang quân"); cụm lạ thì viết hoa từng âm như tên riêng.
    Trả về (bản đã sửa, [(cũ, mới)]).
    """
    table, viet, _syl = _table()
    zh = unicodedata.normalize("NFC", zh or "")
    vi = unicodedata.normalize("NFC", vi or "")
    han = [(m.start() + i, ch) for m in _HAN.finditer(zh) for i, ch in enumerate(m.group())]
    if not han:
        return vi, []
    changes: list[tuple[str, int, int, str]] = []
    for start, end, sylls in _pinyin_runs(vi):
        foreign = any(s not in viet for s in sylls)  # Jun, Huo, Zhu… không thể là tiếng Việt
        if not foreign and not (len(sylls) >= 2 and not _starts_sentence(vi, start)):
            continue
        hit = _match_source(han, sylls, table)
        if hit is None:
            continue
        chars, pys = hit
        if learned and chars in learned:
            new = learned[chars]
            if _starts_sentence(vi, start):
                new = new[:1].upper() + new[1:]
        else:
            hv = reading(chars, list(pys))
            if not hv:
                continue
            new = " ".join(w[:1].upper() + w[1:] for w in hv.split())
        old = vi[start:end]
        if canon(new.replace(" ", "")) == canon(old.replace(" ", "")):
            continue
        changes.append((old, start, end, new))
    for old, start, end, new in sorted(changes, key=lambda c: -c[1]):
        vi = vi[:start] + new + vi[end:]
    return vi, [(old, new) for old, _s, _e, new in changes]


def _match_source(han: list[tuple[int, str]], sylls: tuple[str, ...], table) -> tuple[str, tuple[str, ...]] | None:
    """Dãy chữ Hán liền nhau trong câu gốc có pinyin trùng `sylls` (chữ nào cũng phải khớp)."""
    n = len(sylls)
    for i in range(len(han) - n + 1):
        seq = han[i:i + n]
        if any(seq[j][0] != seq[0][0] + j for j in range(n)):
            continue  # không liền nhau trong câu gốc
        if all(sylls[j] in table.get(seq[j][1], ("", {}))[1] for j in range(n)):
            return "".join(ch for _p, ch in seq), sylls
    return None
