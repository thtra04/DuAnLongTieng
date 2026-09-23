"""Mô hình cue phụ đề + đọc/ghi SRT, VTT, ASS và cắt dòng từ word-timestamps."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .languages import RTL

SENTENCE_END = ".!?…。！？"
CLAUSE_BREAK = ",;:、，；：)]}\"'”’"

# Chữ Hán / Kana / Hangul: viết liền không có dấu cách nên phải ngắt dòng theo
# ký tự, và một dòng chứa được ít ký tự hơn hẳn so với chữ Latin.
CJK_RE = re.compile(r"[぀-ヿ㐀-䶿一-鿿豈-﫿가-힯]")
# Không được để các dấu này đứng đầu dòng mới
NO_LINE_START = "，。、！？；：）】》」』”’,.!?;:)]}"


def is_cjk(text: str) -> bool:
    """Văn bản có phải chủ yếu là chữ Hán/Nhật/Hàn không."""
    letters = [c for c in text if not c.isspace()]
    if not letters:
        return False
    return sum(1 for c in letters if CJK_RE.match(c)) / len(letters) > 0.3


@dataclass
class Cue:
    start: float
    end: float
    text: str
    text2: str = ""  # dòng thứ hai khi xuất phụ đề song ngữ
    speaker: str = ""
    words: list = field(default_factory=list, repr=False)

    def to_dict(self) -> dict:
        return {
            "start": round(self.start, 3),
            "end": round(self.end, 3),
            "text": self.text,
            "text2": self.text2,
            "speaker": self.speaker,
        }

    @staticmethod
    def from_dict(d: dict) -> "Cue":
        return Cue(
            start=float(d.get("start", 0.0)),
            end=float(d.get("end", 0.0)),
            text=(d.get("text") or "").strip(),
            text2=(d.get("text2") or "").strip(),
            speaker=(d.get("speaker") or "").strip(),
        )


# ---------------------------------------------------------------- thời gian


def fmt_srt_time(t: float) -> str:
    if t < 0:
        t = 0.0
    ms = int(round(t * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def fmt_vtt_time(t: float) -> str:
    return fmt_srt_time(t).replace(",", ".")


def fmt_ass_time(t: float) -> str:
    if t < 0:
        t = 0.0
    cs = int(round(t * 100))
    h, cs = divmod(cs, 360_000)
    m, cs = divmod(cs, 6_000)
    s, cs = divmod(cs, 100)
    return f"{h:d}:{m:02d}:{s:02d}.{cs:02d}"


def parse_time(text: str) -> float:
    text = text.strip().replace(",", ".")
    parts = text.split(":")
    try:
        if len(parts) == 3:
            h, m, s = parts
        elif len(parts) == 2:
            h, m, s = "0", parts[0], parts[1]
        else:
            return float(text)
        return int(h) * 3600 + int(m) * 60 + float(s)
    except ValueError:
        return 0.0


# ---------------------------------------------------------------- xuống dòng


def _wrap_cjk(text: str, max_chars: int, max_lines: int) -> str:
    """Ngắt dòng cho chữ viết liền: cắt theo số ký tự, ưu tiên sau dấu câu.

    `max_lines` cố ý KHÔNG dùng để chặn vòng lặp — cùng lý do đã ghi ở
    `wrap_text` cho chữ Latin. Cách cũ dừng sau `max_lines - 1` nhát cắt rồi dồn
    tất cả phần còn lại vào dòng cuối, nên `max_chars` bị vượt thẳng: 80 chữ Hán
    với giới hạn 20 ra dòng đầu 20 chữ và dòng sau **60 chữ**. Đây là ca dùng
    chính của tool (phim Trung), mà thanh trượt số ký tự lại thành vô nghĩa từ
    dòng thứ hai trở đi. Vượt số dòng thì `pipeline._warn_too_many_lines` báo.
    """
    lines: list[str] = []
    rest = text
    while len(rest) > max_chars:
        cut = max_chars
        # lùi lại tìm dấu câu để ngắt cho tự nhiên
        for k in range(max_chars, max(0, max_chars - 6), -1):
            if k < len(rest) and rest[k - 1] in NO_LINE_START:
                cut = k
                break
        # không để dấu câu rơi xuống đầu dòng sau
        while cut < len(rest) and rest[cut] in NO_LINE_START:
            cut += 1
        chunk = rest[:cut].strip()
        if not chunk:
            break  # không cắt thêm được -> dừng, đừng lặp vô hạn
        lines.append(chunk)
        rest = rest[cut:].strip()
    if rest:
        lines.append(rest)
    return "\n".join(lines)


def wrap_text(text: str, max_chars: int = 42, max_lines: int = 2) -> str:
    text = " ".join(text.split())

    if is_cjk(text):
        # một dòng chữ Hán rộng gấp đôi chữ Latin nên chứa được ít ký tự hơn
        limit = max(8, max_chars // 2)
        return text if len(text) <= limit else _wrap_cjk(text, limit, max_lines)

    if len(text) <= max_chars:
        return text

    words = text.split(" ")
    lines: list[str] = []
    cur = ""
    for w in words:
        cand = f"{cur} {w}".strip()
        if len(cand) <= max_chars or not cur:
            cur = cand
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)

    # Cố ý KHÔNG dồn lại thành đúng `max_lines` dòng.
    #
    # Cách cũ chia đều theo SỐ TỪ mà không kiểm độ dài, nên `max_chars` bị vượt
    # thẳng: đặt 42 ra dòng 55 ký tự, và đặt 20 cho ra ĐÚNG kết quả như đặt 42 —
    # thanh trượt thành vô tác dụng (đo thật: 85% dòng vượt khi đặt 42, 98% khi
    # đặt 20). Dòng dài quá đọc không kịp còn tệ hơn thừa một dòng, nên ở đây
    # giữ đúng `max_chars`; ai vượt số dòng thì `pipeline` cảnh báo.
    return "\n".join(_hard_wrap(lines, max_chars))


def _hard_wrap(lines: list[str], max_chars: int) -> list[str]:
    """Chẻ nốt những dòng vẫn dài quá vì có một từ dài hơn cả giới hạn."""
    out: list[str] = []
    for line in lines:
        while len(line) > max_chars:
            out.append(line[:max_chars])
            line = line[max_chars:]
        if line:
            out.append(line)
    return out


def _bidi(text: str, lang: str | None) -> str:
    """Bọc dấu RLE/PDF cho ngôn ngữ viết phải-sang-trái."""
    if lang in RTL:
        return "‫" + text + "‬"
    return text


# ---------------------------------------------------------------- ghi file


def _display(cue: Cue, mode: str, lang: str | None, lang2: str | None) -> str:
    """mode: 'main' | 'second' | 'both' | 'both_rev'"""
    a = cue.text.strip()
    b = cue.text2.strip()
    if mode == "second":
        return _bidi(b or a, lang2 or lang)
    if mode == "both" and b:
        return _bidi(a, lang) + "\n" + _bidi(b, lang2)
    if mode == "both_rev" and b:
        return _bidi(b, lang2) + "\n" + _bidi(a, lang)
    return _bidi(a, lang)


def _body_lines(body: str, max_chars: int, max_lines: int) -> str:
    """Cắt dòng cho phần chữ của một cue.

    Bỏ dòng rỗng: trong SRT/VTT, dòng trống là dấu HẾT cue — để lọt một dòng
    trống vào giữa là mọi chữ phía sau nó bị mất khi đọc lại file.
    """
    parts = [wrap_text(p, max_chars, max_lines) for p in body.split("\n") if p.strip()]
    return "\n".join(p for p in parts if p.strip())


def to_srt(cues: list[Cue], mode: str = "main", lang=None, lang2=None, max_chars=42, max_lines=2) -> str:
    out: list[str] = []
    idx = 0
    for cue in cues:
        body = _display(cue, mode, lang, lang2)
        wrapped = _body_lines(body, max_chars, max_lines)
        if not wrapped:
            continue
        idx += 1
        out.append(f"{idx}\n{fmt_srt_time(cue.start)} --> {fmt_srt_time(cue.end)}\n{wrapped}\n")
    return "\n".join(out)


def to_vtt(cues: list[Cue], mode: str = "main", lang=None, lang2=None, max_chars=42, max_lines=2) -> str:
    out = ["WEBVTT", ""]
    for cue in cues:
        body = _display(cue, mode, lang, lang2)
        wrapped = _body_lines(body, max_chars, max_lines)
        if not wrapped:
            continue
        out.append(f"{fmt_vtt_time(cue.start)} --> {fmt_vtt_time(cue.end)}\n{wrapped}\n")
    return "\n".join(out)


DEFAULT_STYLE = {
    "font": "Arial",
    "size": 46,
    "primary": "#FFFFFF",
    "outline_color": "#000000",
    "back_color": "#000000",
    "outline": 2.5,
    "shadow": 0.6,
    "box": False,      # nền hộp mờ thay vì viền
    "bold": True,
    "italic": False,
    "position": "bottom",  # bottom | middle | top
    "margin_v": 48,
    "play_res_y": 1080,
}


def _ass_color(hex_color: str, alpha: int = 0) -> str:
    """#RRGGBB -> &HAABBGGRR"""
    h = (hex_color or "#FFFFFF").lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    if len(h) != 6:
        h = "FFFFFF"
    r, g, b = h[0:2], h[2:4], h[4:6]
    return f"&H{alpha:02X}{b}{g}{r}".upper()


def to_ass(
    cues: list[Cue],
    mode: str = "main",
    lang=None,
    lang2=None,
    style: dict | None = None,
    max_chars: int = 42,
    max_lines: int = 2,
    play_res_x: int = 1920,
    play_res_y: int = 1080,
) -> str:
    st = {**DEFAULT_STYLE, **(style or {})}
    align = {"bottom": 2, "middle": 5, "top": 8}.get(st.get("position", "bottom"), 2)
    border_style = 3 if st.get("box") else 1
    back_alpha = 0x40 if st.get("box") else 0x80

    # Cỡ chữ do người dùng đặt theo khung 1080p, scale sang độ phân giải thật
    scale = play_res_y / float(st.get("play_res_y", 1080) or 1080)
    size = max(8, int(round(float(st.get("size", 46)) * scale)))
    margin_v = max(0, int(round(float(st.get("margin_v", 48)) * scale)))
    outline = round(float(st.get("outline", 2.5)) * scale, 1)
    shadow = round(float(st.get("shadow", 0.6)) * scale, 1)

    header = f"""[Script Info]
ScriptType: v4.00+
WrapStyle: 0
ScaledBorderAndShadow: yes
YCbCr Matrix: TV.601
PlayResX: {play_res_x}
PlayResY: {play_res_y}

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{st['font']},{size},{_ass_color(st['primary'])},{_ass_color(st['primary'])},{_ass_color(st['outline_color'])},{_ass_color(st['back_color'], back_alpha)},{-1 if st.get('bold') else 0},{-1 if st.get('italic') else 0},0,0,100,100,0,0,{border_style},{outline},{shadow},{align},60,60,{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = [header]
    for cue in cues:
        body = _display(cue, mode, lang, lang2)
        if not body.strip():
            continue
        wrapped = "\n".join(wrap_text(p, max_chars, max_lines) for p in body.split("\n"))
        text = wrapped.replace("\\", "\\\\").replace("\n", "\\N").replace("{", "\\{").replace("}", "\\}")
        lines.append(
            f"Dialogue: 0,{fmt_ass_time(cue.start)},{fmt_ass_time(cue.end)},Default,,0,0,0,,{text}"
        )
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------- đọc file

_SRT_BLOCK = re.compile(
    r"(?:\d+\s*\n)?(\d{1,2}:\d{2}:\d{2}[,.]\d{1,3}|\d{1,2}:\d{2}[,.]\d{1,3})\s*-->\s*"
    r"(\d{1,2}:\d{2}:\d{2}[,.]\d{1,3}|\d{1,2}:\d{2}[,.]\d{1,3})[^\n]*\n(.*?)(?=\n\s*\n|\Z)",
    re.S,
)


def parse_subtitle(raw: str) -> list[Cue]:
    """Đọc SRT hoặc VTT."""
    raw = raw.replace("﻿", "").replace("\r\n", "\n").replace("\r", "\n")
    cues: list[Cue] = []
    for m in _SRT_BLOCK.finditer(raw):
        text = m.group(3).strip()
        text = re.sub(r"<[^>]+>", "", text)  # bỏ tag <i>, <c.xxx>
        if not text:
            continue
        cues.append(Cue(parse_time(m.group(1)), parse_time(m.group(2)), text))
    return cues


def split_plain_text(raw: str) -> list[str]:
    """Tách văn bản thô thành các câu để canh giờ."""
    raw = raw.replace("\r\n", "\n").replace("\r", "\n").strip()
    chunks: list[str] = []
    for para in raw.split("\n"):
        para = para.strip()
        if not para:
            continue
        # tách theo dấu câu, giữ lại dấu
        parts = re.split(r"(?<=[.!?…。！？])\s+", para)
        for p in parts:
            p = p.strip()
            if p:
                chunks.append(p)
    return chunks


# ---------------------------------------------------- cắt cue từ word-timestamps


def cues_from_words(
    words: list[dict],
    max_chars: int = 84,
    max_dur: float = 6.0,
    min_dur: float = 0.7,
    gap_split: float = 0.7,
) -> list[Cue]:
    """Gom danh sách word {word,start,end} thành các cue đọc được.

    Ưu tiên ngắt ở dấu chấm câu, sau đó tới khoảng lặng dài, cuối cùng mới ngắt
    vì quá dài/quá lâu.
    """
    # Chữ Hán/Kana/Hangul đặc hơn chữ Latin nhiều: cùng một số ký tự sẽ chiếm
    # gấp đôi bề ngang và mất gấp mấy lần thời gian đọc.
    if is_cjk("".join(w.get("word", "") for w in words[:400])):
        max_chars = max(16, max_chars // 3)

    cues: list[Cue] = []
    buf: list[dict] = []

    def flush() -> None:
        nonlocal buf
        if not buf:
            return
        text = "".join(w["word"] for w in buf).strip()
        text = re.sub(r"\s+", " ", text)
        if text:
            start = buf[0]["start"]
            end = max(buf[-1]["end"], start + min_dur)
            cues.append(Cue(start, end, text, words=list(buf)))
        buf = []

    for i, w in enumerate(words):
        if not (w.get("word") or "").strip():
            continue
        if buf:
            gap = w["start"] - buf[-1]["end"]
            cur_len = len("".join(x["word"] for x in buf).strip())
            cur_dur = buf[-1]["end"] - buf[0]["start"]
            # Sang đoạn Whisper khác cũng là một ranh giới: đoạn thường là câu/vế
            # trọn, và với chữ Hán (không dấu câu, không dấu cách) đó là mốc duy nhất.
            new_seg = (
                w.get("seg") is not None
                and buf[-1].get("seg") is not None
                and w["seg"] != buf[-1]["seg"]
            )
            if new_seg or gap >= gap_split or cur_len >= max_chars or cur_dur >= max_dur:
                flush()
        buf.append(w)

        stripped = w["word"].strip()
        if stripped and stripped[-1] in SENTENCE_END:
            flush()
        elif stripped and stripped[-1] in CLAUSE_BREAK:
            cur_len = len("".join(x["word"] for x in buf).strip())
            if cur_len >= max_chars * 0.6:
                flush()

    flush()
    return _tidy(cues)


def _tidy(cues: list[Cue], min_dur: float = 0.7, min_gap: float = 0.04) -> list[Cue]:
    """Bảo đảm cue không chồng lấn và không quá ngắn."""
    out: list[Cue] = []
    for cue in cues:
        if not cue.text.strip():
            continue
        if cue.end - cue.start < min_dur:
            cue.end = cue.start + min_dur
        if out:
            prev = out[-1]
            if cue.start < prev.end + min_gap:
                mid = max(prev.start + 0.2, (prev.end + cue.start) / 2)
                prev.end = min(prev.end, mid)
                cue.start = max(cue.start, prev.end + min_gap)
                if cue.end <= cue.start:
                    cue.end = cue.start + min_dur
        out.append(cue)
    return out


def shift_cues(cues: list[Cue], seconds: float) -> list[Cue]:
    for cue in cues:
        cue.start = max(0.0, cue.start + seconds)
        cue.end = max(cue.start + 0.1, cue.end + seconds)
    return cues
