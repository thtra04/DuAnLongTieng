"""Script-local terminology for Chinese dialogue. Guessed names never enter global memory."""
from __future__ import annotations

import re
from dataclasses import dataclass, replace
from functools import lru_cache
from pathlib import Path

from . import hanviet


@dataclass(frozen=True)
class Term:
    vi: str
    kind: str
    gloss: str = ""


@lru_cache(maxsize=1)
def dictionary() -> dict[str, Term]:
    out = {}
    for line in Path(__file__).with_name("hanviet_terms.tsv").read_text(encoding="utf-8").splitlines():
        if line and not line.startswith("#"):
            kind, variants, vi, *gloss = line.split("\t")
            for zh in variants.split("/"):
                out[zh] = Term(vi, kind, next(iter(gloss), ""))
    return out


_FAMILIES = "王李张張刘劉陈陳杨楊黄黃赵趙吴吳周徐孙孫马馬朱胡郭何高林郑鄭罗羅梁宋谢謝唐许許韩韓冯馮邓鄧曹彭萧蕭田董潘袁蔡余于杜叶葉程魏苏蘇吕呂丁任沈姚卢盧姜崔钟鍾白陆陸汪范金石廖贾賈夏韦韋傅方熊秦江史顾顧侯邵孟龙龍万萬钱錢段雷武霍柳楚云雲温溫萧肖曾仇区區单單解"
_READ = {
    "单": "Thiện", "單": "Thiện", "区": "Âu", "區": "Âu", "仇": "Cừu", "曾": "Tăng",
    "司马": "Tư Mã", "司馬": "Tư Mã", "欧阳": "Âu Dương", "歐陽": "Âu Dương",
    "诸葛": "Gia Cát", "諸葛": "Gia Cát", "上官": "Thượng Quan", "慕容": "Mộ Dung",
    "尉迟": "Uất Trì", "尉遲": "Uất Trì", "令狐": "Lệnh Hồ", "长孙": "Trưởng Tôn", "長孫": "Trưởng Tôn",
}
_FAMILY = "(?:" + "|".join(k for k in _READ if len(k) > 1) + f"|[{_FAMILIES}])"
_INTRO = {"我姓": "Họ của tôi là", "敝姓": "Tôi họ", "免贵姓": "Tôi họ", "免貴姓": "Tôi họ",
          "我叫": "Tôi tên là", "我名叫": "Tôi tên là", "在下": "Tại hạ là", "小女子名叫": "Tiểu nữ tên là"}
_TITLE = {"姑娘": "{} cô nương", "公子": "{} công tử", "大人": "{} đại nhân", "将军": "tướng quân {}",
          "將軍": "tướng quân {}", "先生": "ông {}", "女士": "bà {}", "教授": "giáo sư {}",
          "医生": "bác sĩ {}", "醫生": "bác sĩ {}", "警官": "cảnh sát {}", "师傅": "sư phụ {}", "師傅": "sư phụ {}"}
_INTRO_RE = re.compile(r"(?:^|[，,。！？!?；;：:\s])(" + "|".join(_INTRO) + ")(" + _FAMILY
                       + r")([一-鿿]{0,2})(?=$|[，,。！？!?；;：:、.\s])")
_TITLE_RE = re.compile(f"({_FAMILY})(" + "|".join(_TITLE) + ")")
_NOT_GIVEN = set("的了我是你他她在这那有不没沒去来來要很家谁誰叫说說什谁先爷爺吗嗎吧呢啊着过過做事让讓")
_END = re.compile(r"([。！？.!?…]*)$")
_PUNCT = str.maketrans("。！？", ".!?")
_COMPARISON = re.compile(r"(有些事(?:情)?|这些事|這些事)?(知道|了解)(?:的|得)?越(少|多)越(安心|放心|不安|担心|擔心)")


def _family(zh):
    return _READ.get(zh) or (hanviet.reading(zh) or "").title()


def _intro(m):
    lead, family, given = m.group(1, 2, 3)
    if lead.endswith("姓") != (not given) or any(ch in _NOT_GIVEN for ch in given):
        return None
    name = family + given
    if name in dictionary() and dictionary()[name].kind != "person":
        return None
    tail = hanviet.reading(given) if given else ""
    if tail is None or not _family(family):
        return None
    return name, dictionary().get(name, Term((_family(family) + " " + tail.title()).strip(), "person"))


class Lexicon:
    def __init__(self, texts, manual=()):
        script = "\n".join(texts)
        terms = {z: t for z, t in dictionary().items() if z in script}
        for m in _INTRO_RE.finditer(script):
            item = _intro(m)
            if item:
                terms.setdefault(*item)
        for m in _TITLE_RE.finditer(script):
            surname, title = m.groups()
            if _family(surname):
                terms.setdefault(m.group(), Term(_TITLE[title].format(_family(surname)), "person"))
        for z, vi in hanviet.learned_pairs(texts) + list(manual):
            if hanviet.is_han(z):
                prev = terms.get(z, Term(vi, "person" if vi[:1].isupper() else "term"))
                terms[z] = replace(prev, vi=vi, gloss=prev.gloss if vi == prev.vi else "")
        self.terms = terms
        self.pattern = re.compile("|".join(map(re.escape, sorted(terms, key=len, reverse=True)))) if terms else None

    def matches(self, text):
        for m in self.pattern.finditer(text) if self.pattern else ():
            z = m.group()
            if len(z) == 1 and z in _FAMILIES and not (
                text[:m.start()].endswith("姓") or text.strip(" 。！？.!?") == z
            ):
                continue
            if z in ("老爷", "老爺") and text[m.end():m.end()+1] in ("车", "車", "爷", "爺"):
                continue
            yield m

    def suggest(self, texts):
        rows = {}
        for i, text in enumerate(texts):
            for m in self.matches(text):
                z = m.group()
                row = rows.setdefault(z, dict(zh=z, vi=self.terms[z].vi, kind=self.terms[z].kind, first=i, count=0))
                row["count"] += 1
        return list(rows.values())

    def direct(self, text):
        """Only render whole lexical expressions/introductions; never discard an unmatched clause."""
        p = _END.search(text).group()
        body = text[:len(text)-len(p)].strip()
        vi = ""
        if body in self.terms:
            vi = self.terms[body].vi
        elif m := _COMPARISON.fullmatch(body):
            topic, verb, amount, feeling = m.groups()
            vi = (("Có những chuyện, " if topic.startswith("有些") else "Những chuyện này, ") if topic else "")
            vi += ("càng biết " if verb == "知道" else "càng hiểu ") + ("ít" if amount == "少" else "nhiều")
            vi += " càng " + {"安心":"yên lòng", "放心":"yên tâm", "不安":"bất an",
                             "担心":"lo lắng", "擔心":"lo lắng"}[feeling]
        elif (m := _INTRO_RE.fullmatch(body)) and (item := _intro(m)):
            vi = _INTRO[m[1]] + " " + self.terms[item[0]].vi
        elif body[:2] in ("这是", "這是", "那是") and body[2:] in self.terms:
            vi = ("Đó là " if body.startswith("那") else "Đây là ") + self.terms[body[2:]].vi
        elif (m := re.fullmatch(r"(?:管教|保证|保證|包管|保)(你|我|您)(锦衣玉食|錦衣玉食|衣食无忧|衣食無憂|吃穿不愁)", body)):
            vi = "Đảm bảo " + {"我": "tôi ", "您": "quý vị ", "你": ""}[m[1]] + "sẽ " + self.terms[m[2]].vi
        elif body[:2] in ("这些", "這些", "那些") and body[2:] in self.terms:
            t = self.terms[body[2:]]
            if t.kind in ("noun", "idiom") and (t.kind == "noun" or body[2:] in ("粗茶淡饭", "粗茶淡飯")):
                vi = "những " + t.vi + (" kia" if body.startswith("那") else " này")
        return (vi[:1].upper() + vi[1:] + p.translate(_PUNCT)) if vi else ""

    def prepare(self, text, protect=True):
        parts, slots, end = [], {}, 0
        matches = list(self.matches(text))
        # Stacking several paraphrases can change who did what in the surrounding clause.
        keep_context = sum(bool(self.terms[m.group()].gloss) for m in matches) > 1
        for m in matches:
            t = self.terms[m.group()]
            parts.append(text[end:m.start()])
            if protect and t.kind in ("person", "place") and "QZ" not in text.upper():
                token = f"QZ{7011 + len(slots)}"
                slots[token] = t.vi
                parts.append(f" {token} ")
            elif keep_context and t.gloss:
                parts.append(m.group())
            else:
                parts.append(t.gloss or f" {t.vi} ")
            end = m.end()
        return "".join(parts + [text[end:]]).strip(), slots


def restore(text, slots):
    """A dropped/duplicated marker is not a license to guess where a name belongs."""
    if not slots:
        return text
    tokens = re.findall(r"QZ\d+", text, re.I)
    if sorted(x.upper() for x in tokens) != sorted(slots):
        return None
    return re.sub(r"QZ\d+", lambda m: slots[m.group().upper()], text, flags=re.I)
