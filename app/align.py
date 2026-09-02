"""Canh văn bản người dùng cung cấp vào timeline lấy từ word-timestamps của Whisper.

Ý tưởng: chuẩn hoá cả hai chuỗi token (văn bản người dùng và bản Whisper nghe
được), khớp chúng bằng SequenceMatcher, rồi gán mốc thời gian cho từng câu của
người dùng. Câu nào không khớp được thì nội suy tuyến tính giữa hai neo gần nhất.
"""

from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

from .subtitles import Cue, is_cjk, split_plain_text, _tidy


def _norm(token: str) -> str:
    token = unicodedata.normalize("NFKC", token).lower()
    token = re.sub(r"[^\w-￿]+", "", token, flags=re.UNICODE)
    return token


def _tokenize(text: str) -> list[str]:
    return [t for t in re.split(r"\s+", text.strip()) if t]


def align_text(
    user_text: str,
    asr_words: list[dict],
    total_duration: float,
    max_chars: int = 84,
    max_dur: float = 6.5,
) -> list[Cue]:
    """Trả về danh sách Cue mang nội dung của `user_text`, giờ lấy từ `asr_words`."""
    sentences = split_plain_text(user_text)
    if not sentences:
        return []

    # Nếu không có timestamp: chia đều theo độ dài ký tự
    if not asr_words:
        return _even_split(sentences, total_duration, max_chars, max_dur)

    # Token của người dùng, kèm chỉ số câu
    user_tokens: list[str] = []
    token_sent: list[int] = []
    for si, sent in enumerate(sentences):
        for tok in _tokenize(sent):
            n = _norm(tok)
            if n:
                user_tokens.append(n)
                token_sent.append(si)

    asr_tokens: list[str] = []
    asr_index: list[int] = []
    for wi, w in enumerate(asr_words):
        n = _norm(w.get("word", ""))
        if n:
            asr_tokens.append(n)
            asr_index.append(wi)

    if not user_tokens or not asr_tokens:
        return _even_split(sentences, total_duration, max_chars, max_dur)

    matcher = SequenceMatcher(None, user_tokens, asr_tokens, autojunk=False)
    # token người dùng thứ i -> word ASR thứ j
    mapping: dict[int, int] = {}
    for a, b, size in matcher.get_matching_blocks():
        for k in range(size):
            mapping[a + k] = asr_index[b + k]

    audio_end = asr_words[-1]["end"] if asr_words else (total_duration or 0.0)

    # Mốc thời gian cho mỗi câu: lấy min start / max end của các token khớp được
    bounds: list[list[float | None]] = [[None, None] for _ in sentences]
    for ti, si in enumerate(token_sent):
        wi = mapping.get(ti)
        if wi is None:
            continue
        w = asr_words[wi]
        lo, hi = bounds[si]
        bounds[si][0] = w["start"] if lo is None else min(lo, w["start"])
        bounds[si][1] = w["end"] if hi is None else max(hi, w["end"])

    _interpolate(bounds, sentences, audio_end)

    cues: list[Cue] = []
    for si, sent in enumerate(sentences):
        start, end = bounds[si]
        start = 0.0 if start is None else float(start)
        end = float(end) if end is not None else start + 2.0
        if end <= start:
            end = start + max(0.8, len(sent) / 17.0)
        cues.append(Cue(start, end, sent))

    cues = _split_long(cues, max_chars, max_dur)
    return _tidy(cues)


def _interpolate(bounds, sentences, audio_end: float) -> None:
    """Điền mốc thời gian cho các câu không khớp được, dựa theo độ dài ký tự."""
    n = len(sentences)
    lengths = [max(1, len(s)) for s in sentences]

    # đảm bảo neo đầu/cuối
    if bounds[0][0] is None:
        bounds[0][0] = 0.0
    if bounds[-1][1] is None:
        bounds[-1][1] = audio_end or (sum(lengths) / 17.0)

    known = [i for i in range(n) if bounds[i][0] is not None and bounds[i][1] is not None]
    if not known:
        total = bounds[-1][1] or 0.0
        acc = 0.0
        grand = sum(lengths)
        for i in range(n):
            share = total * lengths[i] / grand
            bounds[i][0] = acc
            bounds[i][1] = acc + share
            acc += share
        return

    # trước neo đầu tiên
    first = known[0]
    if first > 0:
        t0 = 0.0 if bounds[0][0] is None else bounds[0][0]
        t1 = bounds[first][0]
        _spread(bounds, lengths, 0, first, t0, t1)

    # giữa các neo
    for a, b in zip(known, known[1:]):
        if b - a > 1:
            _spread(bounds, lengths, a + 1, b, bounds[a][1], bounds[b][0])

    # sau neo cuối
    last = known[-1]
    if last < n - 1:
        t1 = bounds[-1][1] if bounds[-1][1] is not None else audio_end
        _spread(bounds, lengths, last + 1, n, bounds[last][1], t1)

    for i in range(n):
        if bounds[i][0] is None:
            bounds[i][0] = bounds[i - 1][1] if i else 0.0
        if bounds[i][1] is None:
            bounds[i][1] = bounds[i][0] + lengths[i] / 17.0


def _spread(bounds, lengths, lo: int, hi: int, t_start: float, t_end: float) -> None:
    span = max(0.2, (t_end or 0.0) - (t_start or 0.0))
    grand = sum(lengths[lo:hi]) or 1
    acc = t_start or 0.0
    for i in range(lo, hi):
        share = span * lengths[i] / grand
        if bounds[i][0] is None:
            bounds[i][0] = acc
        if bounds[i][1] is None:
            bounds[i][1] = acc + share
        acc = bounds[i][1]


def _split_long(cues: list[Cue], max_chars: int, max_dur: float) -> list[Cue]:
    """Cắt nhỏ cue quá dài, chia thời gian theo tỉ lệ ký tự."""
    out: list[Cue] = []
    for cue in cues:
        text = cue.text.strip()
        dur = cue.end - cue.start
        if len(text) <= max_chars and dur <= max_dur:
            out.append(cue)
            continue

        parts = max(2, int(max(len(text) / max_chars, dur / max_dur)) + 1)
        words = text.split(" ")
        per = max(1, len(words) // parts + (1 if len(words) % parts else 0))
        chunks = [" ".join(words[i : i + per]) for i in range(0, len(words), per)]
        chunks = [c for c in chunks if c]
        grand = sum(len(c) for c in chunks) or 1
        acc = cue.start
        for c in chunks:
            share = dur * len(c) / grand
            out.append(Cue(acc, acc + share, c))
            acc += share
    return out


def _even_split(sentences: list[str], total: float, max_chars: int, max_dur: float) -> list[Cue]:
    total = total or sum(len(s) for s in sentences) / 17.0
    grand = sum(max(1, len(s)) for s in sentences)
    acc = 0.0
    cues: list[Cue] = []
    for s in sentences:
        share = total * max(1, len(s)) / grand
        cues.append(Cue(acc, acc + share, s))
        acc += share
    return _tidy(_split_long(cues, max_chars, max_dur))


# Số ký tự người xem đọc kịp trong một giây (chuẩn phụ đề thông dụng).
CPS_LATIN = 17.0
CPS_CJK = 9.0
MAX_STRETCH = 2.5  # giây — nới tối đa cho một cue


def retime_translation(cues: list[Cue]) -> list[Cue]:
    """Nới cue đang hiện quá nhanh so với tốc độ đọc, lấn vào khoảng lặng phía sau.

    Mốc bắt đầu luôn giữ nguyên để chữ vẫn khớp với lời thoại; chỉ kéo dài phần
    đuôi khi phía sau đang là khoảng lặng.
    """
    for i, cue in enumerate(cues):
        text = cue.text2 or cue.text
        if not text:
            continue
        cps = CPS_CJK if is_cjk(text) else CPS_LATIN
        need = len(text) / cps
        short = need - (cue.end - cue.start)
        if short <= 0.05:
            continue
        room = (cues[i + 1].start - cue.end - 0.05) if i + 1 < len(cues) else 1.5
        cue.end += max(0.0, min(short, MAX_STRETCH, room))
    return cues
