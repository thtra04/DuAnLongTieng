"""HP-5 — rút gọn câu tiếng Việt **không cần AI** cho vòng lặp ngân sách.

`budget.run_loop` cần một "bộ siết" biết viết lại câu ngắn hơn một số âm tiết
cho trước. Với Claude/OpenAI thì nhắc lại kèm giới hạn (`translate.make_tightener`);
nhưng cấu hình C0 của đề tài (dịch Google, không API key) trước đây không có
cách nào siết — vòng lặp chỉ đo rồi để atempo nén. Đo thật trên video bilibili
16 phút: 78/182 câu phải tăng tốc, tràn 26 giây.

Bộ rút gọn này làm việc mà một biên tập viên lồng tiếng làm trước tiên: bỏ từ
đệm, thay cụm dài bằng cụm ngắn cùng nghĩa, bỏ từ chức năng dư. Nó **không**
cắt ý — hết luật mà vẫn dài thì trả câu đã bớt được bao nhiêu hay bấy nhiêu, và
atempo lo phần còn lại như cũ.

Luật xếp theo **tầng**, từ gần như vô hại đến đổi sắc thái nhẹ; chỉ sang tầng
sau khi tầng trước chưa đủ. Mỗi luật là biểu thức chính quy trên ranh giới âm
tiết tiếng Việt (chữ cái có dấu không phải `\\w` trong mọi engine, nên không
dùng `\\b`).
"""

from __future__ import annotations

import re
from typing import Callable

from .duration import syllables

_L = "A-Za-zÀ-ỹ"
_B0 = rf"(?<![{_L}])"   # không có chữ ngay trước
_B1 = rf"(?![{_L}])"    # không có chữ ngay sau
_FLAGS = re.IGNORECASE


def _w(phrase: str) -> str:
    """Mẫu khớp nguyên cụm từ, bất kể hoa thường, cho phép nhiều khoảng trắng."""
    return _B0 + r"\s+".join(map(re.escape, phrase.split())) + _B1


def _subs(pairs: list[tuple[str, str]]) -> list[tuple[re.Pattern, str]]:
    return [(re.compile(_w(a), _FLAGS), b) for a, b in pairs]


def _drops(words: list[str]) -> list[tuple[re.Pattern, str]]:
    return [(re.compile(_w(a), _FLAGS), "") for a in words]


# Tầng 1 — cụm dài → cụm ngắn cùng nghĩa (gần như không đổi sắc thái)
TIER_1 = _subs(
    [
        ("bởi vì", "vì"), ("tại vì", "vì"), ("là bởi vì", "là vì"),
        ("chính vì vậy", "nên"), ("vì vậy", "nên"), ("vì thế", "nên"), ("cho nên", "nên"),
        ("do đó", "nên"), ("bởi vậy", "nên"), ("thế nên", "nên"),
        ("tuy nhiên", "nhưng"), ("mặc dù", "dù"), ("dù cho", "dù"), ("cho dù", "dù"),
        ("như thế nào", "thế nào"), ("làm thế nào", "làm sao"), ("tại sao", "sao"),
        ("vì sao", "sao"), ("điều gì", "gì"), ("cái gì", "gì"), ("bất cứ điều gì", "bất cứ gì"),
        ("bây giờ", "giờ"), ("hiện tại", "giờ"), ("hiện nay", "giờ"), ("lúc này", "giờ"),
        ("ngay lập tức", "ngay"), ("ngày hôm nay", "hôm nay"), ("ngày hôm qua", "hôm qua"),
        ("tối hôm nay", "tối nay"), ("sáng hôm nay", "sáng nay"),
        ("tất cả mọi người", "mọi người"), ("tất cả các", "các"), ("tất cả những", "những"),
        ("tất cả chúng ta", "chúng ta"), ("tất cả chúng tôi", "chúng tôi"),
        ("một chút", "chút"), ("một lát", "lát"), ("một ít", "ít"),
        ("rất là", "rất"), ("khá là", "khá"), ("rất nhiều", "nhiều"),
        ("vô cùng", "rất"), ("cực kỳ", "rất"), ("cực kì", "rất"), ("hết sức", "rất"),
        ("cũng như", "và"), ("trong trường hợp", "lỡ"), ("đặc biệt là", "nhất là"),
        ("đã từng", "từng"), ("có lẽ là", "có lẽ"), ("có phải là", "có phải"),
        ("chúng ta", "ta"), ("của chúng ta", "của ta"),
        ("một cách nhanh chóng", "nhanh"), ("một cách dễ dàng", "dễ dàng"),
        ("một cách", ""), ("hay là", "hay"), ("hoặc là", "hoặc"), ("nếu như", "nếu"),
        ("thế nhưng", "nhưng"), ("nhưng mà", "nhưng"), ("vậy thì", "vậy"), ("thế thì", "vậy"),
        ("quý vị", "mọi người"), ("các vị", "mọi người"), ("hãy để", "để"),
    ]
)

# Tầng 2 — từ dẫn, từ đệm đầu câu không mang nghĩa (chỉ ở đầu câu — "người này" phải giữ "này")
_LEAD_WORDS = ["thực ra", "thật ra", "nói thật", "quả thật", "thực tế là", "sự thật là", "ý tôi là",
               "bạn biết đấy", "à", "ừm", "ờ", "ơ", "này", "ôi", "hãy", "thế", "vậy", "được rồi"]
TIER_2_LEAD = [
    (re.compile(r"(^|[.!?…]\s+)(?:" + "|".join(_w(x) for x in _LEAD_WORDS) + r")[,!]?\s*", _FLAGS), r"\1"),
] + _drops(["thật sự", "thực sự"])
# Trợ từ cuối câu: chỉ bỏ khi đứng ngay trước dấu câu/cuối chuỗi
_FINAL_PARTICLES = ["nhé", "nha", "nhỉ", "ạ", "à", "thôi", "mà", "đấy", "đó", "cơ", "ấy", "nào"]
# "điều đó", "ở đó"… thì "đó" là đại từ, không phải trợ từ
_NOT_PARTICLE_BEFORE = {"điều", "việc", "cái", "chỗ", "người", "lúc", "ở", "chuyện", "thứ",
                        "nơi", "từ", "kẻ", "đứa", "con", "cô", "anh", "ông", "bà", "chị", "em",
                        "là", "sau", "trước", "khi", "nghe", "thế"}
_FINAL_RE = re.compile(
    rf"(?P<prev>[{_L}]+)\s+(?P<p>" + "|".join(map(re.escape, _FINAL_PARTICLES)) + r")(?=\s*[.!?…,;:]|\s*$)",
    _FLAGS,
)
TIER_2 = _subs([("là một", "là"), ("là những", "là"), ("có một", "có")])

# Tầng 3 — từ chức năng dư trong ngữ cảnh cụ thể
_RANG_AFTER = ["nói", "biết", "nghĩ", "thấy", "tin", "bảo", "hiểu", "nhớ", "hy vọng", "mong",
               "chắc", "sợ", "nghe", "đoán", "cảm thấy", "khẳng định", "thừa nhận"]
TIER_3 = [
    (re.compile(rf"({_B0}(?:{'|'.join(_RANG_AFTER)}))\s+rằng{_B1}", _FLAGS), r"\1"),
    (re.compile(rf"({_B0}(?:{'|'.join(_RANG_AFTER)}))\s+là{_B1}(?=\s+[{_L}])", _FLAGS), r"\1"),
    # "cha của bạn" → "cha bạn": bỏ "của" trước đại từ
    (re.compile(
        rf"([{_L}]+)\s+của\s+(?=(?:chúng|tôi|bạn|anh|em|cô|chú|ta|mình|nó|họ|ông|bà|cậu|cháu|con|mẹ|bố){_B1})",
        _FLAGS), r"\1 "),
    # "có thể ... được" → bỏ "được" cuối
    (re.compile(rf"(có\s+thể\s+[^.!?,;]*?)\s+được(?=\s*[.!?…,;:]|\s*$)", _FLAGS), r"\1"),
    (re.compile(_w("đang"), _FLAGS), ""),
    (re.compile(_w("sẽ"), _FLAGS), ""),
]
# "đã" chỉ bỏ khi câu đã có dấu hiệu quá khứ khác
_PAST_MARKERS = re.compile(_w("rồi") + "|" + _w("từng") + "|" + _w("hôm qua") + "|" + _w("trước đây")
                           + "|" + _w("xưa") + "|" + _w("vừa"), _FLAGS)
_DA = re.compile(_w("đã"), _FLAGS)

# Tầng 4 — phó từ mức độ (đổi sắc thái nhẹ)
TIER_4 = _drops(["rất", "quá", "lắm", "thật", "khá", "hơi", "cũng", "luôn", "hẳn", "quả là", "hãy"])

TIER_NAMES = ("cụm ngắn hơn", "từ đệm", "từ chức năng", "phó từ mức độ")


def _tidy(text: str) -> str:
    """Dọn khoảng trắng và dấu câu sau khi bỏ từ; viết hoa lại chữ đầu câu."""
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\s+([.!?…,;:])", r"\1", text)
    text = re.sub(r"([,;:])\s*\1+", r"\1", text)          # ",," → ","
    text = re.sub(r"^[\s,;:]+", "", text)                  # dấu phẩy mồ côi đầu câu
    text = re.sub(r"([.!?…])\s*[,;:]+", r"\1", text)
    text = text.strip()

    def cap(m: re.Match) -> str:
        return m.group(1) + m.group(2).upper()

    text = re.sub(rf"(^|[.!?…]\s+)([{_L}])", cap, text)
    return text


def _apply(text: str, rules: list[tuple[re.Pattern, str]], target: int) -> str:
    for pat, rep in rules:
        if syllables(text) <= target:
            break
        new = pat.sub(rep, text)
        if new != text:
            text = _tidy(new)
    return text


def _drop_final_particles(text: str, target: int) -> str:
    """Bỏ trợ từ cuối câu ("nhé", "đấy"…) cho tới khi vừa; "điều đó", "ở đó" thì giữ."""
    state = {"text": text}

    def rep(m: re.Match) -> str:
        if m.group("prev").lower() in _NOT_PARTICLE_BEFORE or syllables(state["text"]) <= target:
            return m.group(0)
        state["text"] = state["text"].replace(m.group(0), m.group("prev"), 1)
        return m.group("prev")

    new = _FINAL_RE.sub(rep, text)
    return _tidy(new) if new != text else text


def shorten(text: str, target: int, max_tier: int = 4) -> tuple[str, int]:
    """Rút gọn `text` về ≤ `target` âm tiết nếu được. Trả về (câu mới, tầng cao nhất đã dùng).

    Tầng 0 nghĩa là không phải sửa gì (hoặc không sửa được gì). Không bao giờ
    cắt bớt ý: hết luật mà vẫn dài thì trả câu đã ngắn hơn phần nào.
    """
    text = (text or "").strip()
    if not text or syllables(text) <= target:
        return text, 0
    used = 0
    tiers: list[Callable[[str], str]] = [
        lambda t: _apply(t, TIER_1, target),
        lambda t: _drop_final_particles(_apply(_apply(t, TIER_2_LEAD, target), TIER_2, target), target),
        lambda t: _apply(_DA_rules(t), TIER_3, target),
        lambda t: _apply(t, TIER_4, target),
    ]
    for n, step in enumerate(tiers[:max_tier], start=1):
        new = step(text)
        if new != text:
            text, used = new, n
        if syllables(text) <= target:
            break
    return text, used


def _DA_rules(text: str) -> str:
    if _PAST_MARKERS.search(text):
        return _tidy(_DA.sub("", text))
    return text


def shorten_pieces(pieces: list[str], target: int, max_tier: int = 4) -> tuple[list[str], int]:
    """Rút gọn một câu đang nằm rải trên nhiều cue, **giữ nguyên ranh giới cue**.

    Mỗi mảnh được chia phần ngân sách theo tỉ lệ âm tiết của nó; mảnh nào bớt
    được thì bớt, phần thiếu dồn sang các mảnh sau. Trả về (các mảnh mới, tầng cao nhất).
    """
    syl = [syllables(p) for p in pieces]
    total = sum(syl)
    if total <= target or total == 0:
        return list(pieces), 0
    need = total - target
    out: list[str] = []
    used = 0
    for p, n in zip(pieces, syl):
        share = min(need, max(1, round(need * n / total)) if need > 0 else 0)
        if share <= 0 or n <= 1:
            out.append(p)
            continue
        new, tier = shorten(p, n - share, max_tier)
        if new and p and p[0].islower() and new[0].isupper():
            new = new[0].lower() + new[1:]   # mảnh giữa câu thì không viết hoa
        used = max(used, tier)
        need -= n - syllables(new)
        out.append(new)
    return out, used


def make_tightener(on_log: Callable[[str], None] | None = None, max_tier: int = 4):
    """Bộ siết cho `budget.run_loop`: rút gọn từng câu về `target_syllables` bằng luật."""

    def tighten(requests: list[dict]) -> list:
        out: list = []
        tiers_used = [0] * (len(TIER_NAMES) + 1)
        for r in requests:
            target = int(r.get("target_syllables") or 1)
            pieces = [p for p in (r.get("pieces") or [])]
            if len(pieces) > 1:
                new, tier = shorten_pieces(pieces, target, max_tier)
            else:
                new, tier = shorten(r["text"], target, max_tier)
            tiers_used[tier] += 1
            out.append(new)
        if on_log:
            parts = [f"{TIER_NAMES[i - 1]}: {n}" for i, n in enumerate(tiers_used) if i and n]
            on_log("  Rút gọn bằng luật (không cần AI) — " + (", ".join(parts) if parts else "không câu nào bớt được") + ".")
        return out

    return tighten
