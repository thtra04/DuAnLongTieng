"""Các engine dịch: Google/Bing/MyMemory (online, miễn phí), NLLB-200 (offline),
Claude / OpenAI (AI API, hiểu ngữ cảnh cả đoạn)."""

from __future__ import annotations

import json
import hashlib
import os
import re
import threading
import time
from typing import Callable

from .languages import google_code, name_en, nllb_code
from .subtitles import SENTENCE_END, Cue

_CACHE_LOCK = threading.Lock()
_CACHE_FILE = None


def _translation_cache_file():
    from ..config import DATA_DIR

    global _CACHE_FILE
    if _CACHE_FILE is None:
        _CACHE_FILE = DATA_DIR / "translation_cache.json"
    return _CACHE_FILE


def _cache_key(texts, source, target, engine, model, note, mode, glossary, base_url="", extra=None) -> str:
    payload = json.dumps(
        {
            **({"extra": extra} if extra else {}),
            "texts": texts,
            "source": source,
            "target": target,
            "engine": engine,
            "model": model,
            "note": note,
            "mode": mode,
            "glossary": glossary,
            "base_url": base_url,
        },
        ensure_ascii=False,
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _read_cached(key: str):
    try:
        with _CACHE_LOCK:
            path = _translation_cache_file()
            if not path.exists():
                return None
            data = json.loads(path.read_text(encoding="utf-8"))
        value = data.get(key)
        return value if isinstance(value, list) and len(value) else None
    except (OSError, ValueError, TypeError):
        return None


def _write_cached(key: str, value: list[str]) -> None:
    try:
        with _CACHE_LOCK:
            path = _translation_cache_file()
            data = {}
            if path.exists():
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, ValueError, TypeError):
                    data = {}
            if not isinstance(data, dict):
                data = {}
            data[key] = value
            path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def cache_info() -> dict:
    path = _translation_cache_file()
    try:
        with _CACHE_LOCK:
            data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        return {"entries": len(data) if isinstance(data, dict) else 0, "bytes": path.stat().st_size if path.exists() else 0}
    except (OSError, ValueError, TypeError):
        return {"entries": 0, "bytes": 0}


def clear_cache() -> int:
    path = _translation_cache_file()
    try:
        with _CACHE_LOCK:
            if not path.exists():
                return 0
            data = json.loads(path.read_text(encoding="utf-8"))
            count = len(data) if isinstance(data, dict) else 0
            path.unlink()
            return count
    except (OSError, ValueError, TypeError):
        return 0

ENGINES = [
    {
        "id": "google",
        "label": "Google Translate (miễn phí)",
        "desc": "Nhanh, 100+ ngôn ngữ, không cần API key. Cần mạng.",
        "needs_key": False,
    },
    {
        "id": "mymemory",
        "label": "MyMemory (miễn phí, dự phòng)",
        "desc": "Dùng khi Google bị chặn. Giới hạn ~5000 ký tự/ngày mỗi IP.",
        "needs_key": False,
    },
    {
        "id": "nllb",
        "label": "NLLB-200 (offline, chạy trên máy)",
        "desc": "Không cần mạng. Lần đầu tải model ~2.5 GB. Cần cài nhóm `offline`.",
        "needs_key": False,
    },
    {
        "id": "claude",
        "label": "Claude API (chất lượng cao nhất)",
        "desc": "Dịch cả đoạn, hiểu ngữ cảnh & giữ giọng văn. Cần API key, trả phí.",
        "needs_key": True,
    },
    {
        "id": "openai",
        "label": "OpenAI API",
        "desc": "Tương tự Claude. Cần API key, trả phí.",
        "needs_key": True,
    },
]


class TranslateError(RuntimeError):
    pass


# Mỗi engine cần những gói nào, và bảo người dùng cài thế nào nếu thiếu.
#
# Câu gợi ý cố ý nói "thêm --extra X vào lệnh đang dùng" chứ không đưa một lệnh
# trần kiểu `uv sync --extra ai`: `uv sync` làm môi trường khớp ĐÚNG danh sách
# extra được nêu, nên chạy lệnh trần đó sẽ gỡ luôn torch, VieNeu, pyannote đã cài.
def _need_extra(group: str) -> str:
    return (f"Chưa cài nhóm {group}: thêm --extra {group} vào lệnh uv sync đang dùng "
            f"(ví dụ: uv sync --extra cuda --extra {group}; xem README).")


_ENGINE_NEEDS: dict[str, tuple[tuple[str, ...], str]] = {
    "google": (("deep_translator",), "Thiếu gói `deep-translator`."),
    "mymemory": (("deep_translator",), "Thiếu gói `deep-translator`."),
    "nllb": (("torch", "transformers"), _need_extra("offline")),
    "claude": (("anthropic",), _need_extra("ai")),
    "openai": (("openai",), _need_extra("ai")),
}


def engine_available(engine: str) -> tuple[bool, str]:
    """Engine dịch này dùng được chưa, kèm lý do nếu chưa.

    Dùng `find_spec` chứ KHÔNG `import` thật. `/api/system` gọi hàm này cho cả
    5 engine mỗi lần mở trang, mà riêng nhánh `nllb` phải nạp torch và
    transformers — đo thật: 3,5 giây cho một lần mở trang, mỗi lần. `find_spec`
    chỉ tra xem gói có tồn tại hay không nên gần như tức thì.

    Đánh đổi: gói có mặt nhưng hỏng (thiếu DLL, sai phiên bản) vẫn bị báo là
    dùng được. Lỗi đó sẽ bung ra lúc dịch thật, kèm thông báo cụ thể hơn nhiều
    so với một dòng "chưa cài" chung chung ở đây.
    """
    import importlib.util

    need = _ENGINE_NEEDS.get(engine)
    if need is None:
        return False, f"Engine không hợp lệ: {engine}"

    modules, how_to_fix = need
    try:
        for name in modules:
            if importlib.util.find_spec(name) is None:
                return False, how_to_fix
    except (ImportError, ValueError):
        return False, how_to_fix
    return True, ""


# ------------------------------------------------------- gom cue thành câu

# Whisper cắt cue theo độ dài/khoảng lặng nên một câu thường nằm vắt qua nhiều
# cue. Dịch từng mảnh rời sẽ ra kết quả sai nghĩa, nhất là với tiếng Trung/Nhật.
# Vì vậy ta gom các cue thuộc cùng một câu lại, dịch trọn câu, rồi chia bản dịch
# về lại từng cue theo tỉ lệ độ dài.
GROUP_MAX_CUES = 6
GROUP_MAX_CHARS = 240
GROUP_MAX_GAP = 1.5  # giây — im lặng dài hơn ngần này coi như sang câu khác

_CJK = re.compile(r"[぀-ヿ㐀-䶿一-鿿豈-﫿]")
_CLOSERS = "\"'”’)]}»"


def _ends_sentence(text: str) -> bool:
    return bool(text) and text.rstrip().rstrip(_CLOSERS)[-1:] in SENTENCE_END


def _cue_seg(cue: Cue):
    """Chỉ số đoạn Whisper mà cue này thuộc về (asr gắn vào từng từ), nếu có."""
    words = getattr(cue, "words", None) or []
    return words[0].get("seg") if words and isinstance(words[0], dict) else None


def _cjk_segment_break(prev: Cue, cue: Cue, split_lines: bool = False) -> bool:
    """Chữ Hán/Nhật không có dấu câu nên không biết câu kết thúc ở đâu; coi mỗi
    cue là một câu, trừ khi hai cue thuộc cùng một đoạn Whisper (bị chẻ vì quá
    dài). Gộp rồi chia ngược theo tỉ lệ ký tự làm bản dịch lệch dòng (đo thật:
    dòng sau hiện đuôi câu trước)."""
    text = prev.text.strip()
    if not _CJK.search(text) or _ends_sentence(text):
        return False
    a, b = _cue_seg(prev), _cue_seg(cue)
    if a is None or b is None:
        # Không có thông tin đoạn (phụ đề .srt nạp vào, hoặc cue nạp lại từ
        # state.json lúc xuất). Lúc dịch thì mỗi dòng một câu; lúc lồng tiếng
        # thì để các luật gộp thường (khoảng lặng, số cue) quyết định.
        return split_lines
    return a != b


def group_cues(cues: list[Cue], split_cjk_lines: bool = False) -> list[list[int]]:
    """Chia chỉ số cue thành từng nhóm, mỗi nhóm cố gắng là một câu trọn vẹn.

    `split_cjk_lines=True` (bước dịch): cue chữ Hán/Nhật không dấu câu mà không
    biết chắc là cùng một đoạn Whisper thì mỗi cue một nhóm — gộp rồi chia lại
    theo tỉ lệ ký tự làm bản dịch lệch dòng. Mặc định False cho khâu lồng tiếng:
    ở đó gộp thành câu đọc dài vẫn hay hơn (đo thật: tách từng cue làm số câu
    phải nén tăng từ 17 % lên 28 %)."""
    groups: list[list[int]] = []
    cur: list[int] = []
    cur_chars = 0

    def flush() -> None:
        nonlocal cur, cur_chars
        if cur:
            groups.append(cur)
            cur, cur_chars = [], 0

    for i, cue in enumerate(cues):
        text = cue.text.strip()
        if cur:
            prev = cues[cur[-1]]
            gap = cue.start - prev.end
            if (
                gap > GROUP_MAX_GAP
                or len(cur) >= GROUP_MAX_CUES
                or cur_chars + len(text) > GROUP_MAX_CHARS
                or _cjk_segment_break(prev, cue, split_cjk_lines)
            ):
                flush()
        cur.append(i)
        cur_chars += len(text)
        if _ends_sentence(text):
            flush()
    flush()
    return groups


def _join_fragments(parts: list[str]) -> str:
    """Nối các mảnh của cùng một câu; tiếng Trung/Nhật thì không chèn dấu cách."""
    out = ""
    for part in parts:
        if not part:
            continue
        if out and not (_CJK.search(out[-1]) and _CJK.search(part[0])):
            out += " "
        out += part
    return out


def _cut_near(text: str, idx: int, low: int, window: int = 14) -> int:
    """Dời điểm cắt về khoảng trắng gần nhất để không cắt giữa một từ."""
    if " " not in text:  # tiếng Trung/Nhật: cắt ở đâu cũng được
        return idx
    for d in range(window + 1):
        for cand in (idx - d, idx + d):
            if low < cand < len(text) and text[cand] == " ":
                return cand
    return idx


def split_proportional(text: str, weights: list[float]) -> list[str]:
    """Chia `text` thành len(weights) phần, độ dài tỉ lệ theo `weights`."""
    n = len(weights)
    text = (text or "").strip()
    if n <= 1:
        return [text] if n == 1 else []
    if not text:
        return [""] * n

    total = float(sum(weights)) or float(n)
    cuts: list[int] = []
    acc = 0.0
    prev = 0
    for w in weights[:-1]:
        acc += w
        idx = _cut_near(text, int(round(len(text) * acc / total)), prev)
        idx = max(prev, min(len(text), idx))
        cuts.append(idx)
        prev = idx

    parts: list[str] = []
    prev = 0
    for idx in cuts:
        parts.append(text[prev:idx].strip())
        prev = idx
    parts.append(text[prev:].strip())
    return parts


# ---------------------------------------------------------------- điều phối


def translate_cues(
    cues: list[Cue],
    source: str | None,
    target: str,
    engine: str = "google",
    api_key: str = "",
    model: str = "",
    base_url: str = "",
    context_note: str = "",
    translation_mode: str = "natural",
    glossary: str = "",
    on_progress: Callable[[float], None] | None = None,
    on_log: Callable[[str], None] | None = None,
    cast: list[dict] | None = None,
    auto_context: bool = True,
    use_memory: bool = True,
) -> list[Cue]:
    """Dịch nội dung `text` của từng cue, ghi kết quả vào `text2`.

    `cast` là bảng vai của bước tách giọng (`id`, `name`, `gender`, `age`): engine AI
    được biết ai đang nói từng câu để chọn xưng hô. `auto_context` cho engine AI đọc
    lướt kịch bản một lượt trước khi dịch. `use_memory` dùng lại những câu người dùng
    đã sửa tay ở các dự án trước (bộ nhớ dịch).

    Đơn vị gửi đi dịch là **câu** chứ không phải cue: các cue thuộc cùng một câu
    được ghép lại, dịch một lần rồi chia ngược về từng cue. Nhờ vậy bản dịch
    đúng ngữ pháp và khớp với chữ đang hiện trên màn hình.
    """
    if not any(c.text.strip() for c in cues):
        return cues

    ok, reason = engine_available(engine)
    if not ok:
        raise TranslateError(reason)

    groups = group_cues(cues, split_cjk_lines=True)
    texts = [_join_fragments([cues[i].text.strip() for i in g]) for g in groups]
    if on_log and len(groups) < len(cues):
        on_log(f"Gom {len(cues)} dòng thành {len(groups)} câu để dịch trọn ý.")

    is_ai = engine in ("claude", "openai")
    speakers = _speaker_labels(cues, groups, cast) if is_ai else None
    examples: list[tuple[str, str]] = []
    remembered: dict[int, str] = {}
    if use_memory:
        remembered, examples = _recall(texts, source, target, on_log)

    out = None
    cache_key = None
    if is_ai:
        cache_model = model or ("claude-opus-5" if engine == "claude" else "gpt-4o-mini")
        extra = {"ctx": 2, "speakers": speakers, "brief": bool(auto_context), "examples": examples}
        cache_key = _cache_key(
            texts, source, target, engine, cache_model,
            context_note, translation_mode, glossary, base_url,
            extra=extra if (speakers or auto_context or examples) else {"ctx": 2},
        )
        out = _read_cached(cache_key)
        if out is not None:
            if on_log:
                on_log(f"Dùng bản dịch AI đã lưu trong cache ({len(out)} câu), không gọi API lại.")
            if on_progress:
                on_progress(1.0)

    if engine in ("google", "mymemory", "nllb"):
        # Engine miễn phí không nhận chỉ dẫn, nên bộ thuật ngữ được cài thẳng vào câu
        # gốc trước khi gửi đi: tên riêng và xưng hô ra đúng như người dùng đã ghi.
        pairs = parse_glossary(glossary)
        sent, used = apply_glossary(texts, pairs)
        if used and on_log:
            on_log(f"Áp bộ thuật ngữ vào {used} câu trước khi dịch ({len(pairs)} mục).")
        if engine == "nllb":
            out = _translate_nllb(sent, source, target, on_progress, on_log)
        else:
            out = _translate_deep(sent, source, target, engine, on_progress, on_log)
    elif is_ai and out is None:
        out = _translate_ai(
            engine, texts, source, target, api_key, model, base_url, context_note,
            translation_mode, glossary, on_progress, on_log,
            speakers=speakers, cast=cast, auto_context=auto_context, examples=examples,
        )
    elif not is_ai:
        raise TranslateError(f"Engine không hỗ trợ: {engine}")

    if cache_key is not None and out is not None:
        _write_cached(cache_key, out)

    # Câu người dùng từng sửa tay thắng mọi engine: họ đã quyết định câu đó rồi.
    for i, tr in remembered.items():
        out[i] = tr

    _warn_long_translations(texts, out, translation_mode, on_log)

    for g, tr in zip(groups, out):
        tr = (tr or "").strip()
        if len(g) == 1:
            cues[g[0]].text2 = tr
            continue
        weights = [max(1, len(cues[i].text.strip())) for i in g]
        for i, part in zip(g, split_proportional(tr, weights)):
            cues[i].text2 = part
    return cues


# ---------------------------------------------------------- deep-translator


# Endpoint "gtx" của Google Dịch: trả JSON, giữ nguyên xuống dòng nên gộp được
# nhiều câu một lượt mà không cần ký tự phân cách lạ. Đo thật (9/2026): trang
# translate.google.com/m mà deep-translator dùng làm hỏng ký tự phân cách với
# chữ Hán -> tool rơi về dịch từng dòng, 270 lượt liên tiếp -> Google chặn IP
# ("too many requests") và toàn bộ bản dịch trống. Đường gtx đi trước; đường
# cũ giữ làm dự phòng, có giãn nhịp.
_GTX_URL = "https://translate.googleapis.com/translate_a/single"
_GTX_MAX_LINES = 40
_GTX_MAX_CHARS = 1500
# Google cho ~5 lượt/giây; dịch từng dòng thì giãn ra cho chắc.
_LINE_PAUSE = 0.35
# Bị chặn ("too many requests") thì chờ ngần này giây trước mỗi lần thử lại.
_BLOCK_BACKOFF = (10.0, 20.0, 40.0)


def _is_rate_limited(exc: BaseException) -> bool:
    low = str(exc).lower()
    return "too many requests" in low or "429" in low


def _gtx_call(text: str, src: str, tgt: str, timeout: float = 30.0) -> str:
    """Một lượt gọi gtx. Trả về chuỗi dịch, xuống dòng giữ nguyên như đầu vào."""
    import urllib.parse
    import urllib.request

    body = urllib.parse.urlencode(
        {"client": "gtx", "sl": src, "tl": tgt, "dt": "t", "q": text}
    ).encode("utf-8")
    req = urllib.request.Request(
        _GTX_URL,
        data=body,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    parts = data[0] if isinstance(data, list) and data else []
    return "".join(p[0] for p in parts if isinstance(p, list) and p and p[0])


def _gtx_batches(texts: list[str]) -> list[list[int]]:
    batches: list[list[int]] = []
    cur: list[int] = []
    cur_len = 0
    for i, t in enumerate(texts):
        add = len(t) + 1
        if cur and (cur_len + add > _GTX_MAX_CHARS or len(cur) >= _GTX_MAX_LINES):
            batches.append(cur)
            cur, cur_len = [], 0
        cur.append(i)
        cur_len += add
    if cur:
        batches.append(cur)
    return batches


def _translate_gtx(
    texts: list[str], src: str, tgt: str, on_progress=None, on_log=None, call=None
) -> list[str]:
    """Dịch qua gtx: mỗi lô nhiều dòng nối bằng xuống dòng; lô nào tách sai thì
    dịch từng dòng của lô đó (có giãn nhịp). Bị chặn thì lùi rồi thử lại; hết
    kiên nhẫn thì ném lỗi để người dùng biết, thay vì trả bản dịch trống."""
    call = call or _gtx_call
    results = [""] * len(texts)
    clean = [re.sub(r"\s*\n\s*", " ", t).strip() for t in texts]

    def attempt(payload: str) -> str:
        last: BaseException | None = None
        for k, wait in enumerate((0.0,) + _BLOCK_BACKOFF):
            if wait:
                if on_log:
                    on_log(f"Google tạm chặn vì gọi quá nhiều — chờ {wait:.0f}s rồi thử lại…")
                time.sleep(wait)
            try:
                return call(payload, src, tgt)
            except Exception as exc:  # noqa: BLE001
                last = exc
                if not _is_rate_limited(exc):
                    raise
        raise TranslateError(
            "Google Dịch đang chặn máy này vì gọi quá nhiều lượt. Đợi vài phút rồi "
            f"thử lại, hoặc chọn engine dịch khác. ({last})"
        )

    batches = _gtx_batches(clean)
    done = 0
    for bi, batch in enumerate(batches):
        joined = "\n".join(clean[i] or "…" for i in batch)
        raw = attempt(joined)
        parts = [p.strip() for p in raw.split("\n")]
        if len(parts) != len(batch):
            if on_log:
                on_log(f"Lô {bi + 1}: Google gộp/tách dòng khác đầu vào — dịch từng dòng của lô này.")
            parts = []
            for i in batch:
                parts.append(attempt(clean[i]).strip() if clean[i] else "")
                time.sleep(_LINE_PAUSE)
        for i, val in zip(batch, parts):
            results[i] = val if clean[i] else ""
        done += len(batch)
        if on_progress:
            on_progress(done / max(1, len(texts)))
        if bi + 1 < len(batches):
            time.sleep(_LINE_PAUSE)
    return results


def _translate_deep(
    texts: list[str],
    source: str | None,
    target: str,
    engine: str,
    on_progress=None,
    on_log=None,
) -> list[str]:
    src = google_code(source) if source else "auto"
    tgt = google_code(target)

    if engine == "google":
        try:
            return _translate_gtx(texts, src, tgt, on_progress, on_log)
        except TranslateError:
            raise
        except Exception as exc:  # noqa: BLE001 — mạng/endpoint đổi -> đường cũ
            if on_log:
                on_log(f"Đường gtx không dùng được ({str(exc)[:80]}) — dùng deep-translator…")

    from deep_translator import GoogleTranslator, MyMemoryTranslator

    if engine == "mymemory":
        if src == "auto":
            src = "en"
        tr = MyMemoryTranslator(source=src, target=tgt)
    else:
        tr = GoogleTranslator(source=src, target=tgt)

    results: list[str] = [""] * len(texts)
    # Gộp nhiều cue vào một request bằng ký tự phân tách hiếm gặp
    SEP = "\n⟦⟧\n"
    batches: list[list[int]] = []
    cur: list[int] = []
    cur_len = 0
    for i, t in enumerate(texts):
        add = len(t) + len(SEP)
        if cur and (cur_len + add > 3500 or len(cur) >= 40):
            batches.append(cur)
            cur, cur_len = [], 0
        cur.append(i)
        cur_len += add
    if cur:
        batches.append(cur)

    done = 0
    for bi, batch in enumerate(batches):
        joined = SEP.join(texts[i] if texts[i] else "…" for i in batch)
        translated: list[str] | None = None
        for attempt in range(3):
            try:
                raw = tr.translate(joined) or ""
                parts = [p.strip() for p in re.split(r"⟦\s*⟧", raw)]
                if len(parts) == len(batch):
                    translated = parts
                    break
                # tách sai -> dịch từng dòng
                translated = None
                break
            except Exception as exc:
                if attempt == 2:
                    if on_log:
                        on_log(f"Lỗi batch {bi + 1}: {exc} — chuyển sang dịch từng dòng")
                    translated = None
                else:
                    time.sleep(1.2 * (attempt + 1))

        if translated is None:
            translated = []
            for i in batch:
                translated.append(_translate_one(tr, texts[i], on_log))
        for i, val in zip(batch, translated):
            results[i] = val
        done += len(batch)
        if on_progress:
            on_progress(done / max(1, len(texts)))

    return results


def _translate_one(tr, text: str, on_log=None) -> str:
    """Dịch một dòng bằng deep-translator, có giãn nhịp và lùi khi bị chặn.

    Bị chặn liên tục thì ném TranslateError: bản dịch trống lặng lẽ tệ hơn
    một thông báo rõ ràng (đo thật: cả video ra phụ đề rỗng mà không ai biết).
    """
    if not text.strip():
        return ""
    time.sleep(_LINE_PAUSE)
    last: BaseException | None = None
    for attempt, wait in enumerate((0.0,) + _BLOCK_BACKOFF):
        if wait:
            if on_log:
                on_log(f"Google tạm chặn vì gọi quá nhiều — chờ {wait:.0f}s rồi thử lại…")
            time.sleep(wait)
        try:
            return (tr.translate(text) or "").strip()
        except Exception as exc:  # noqa: BLE001
            last = exc
            if not _is_rate_limited(exc):
                if attempt >= 2:
                    if on_log:
                        on_log(f"Bỏ qua 1 dòng do lỗi: {exc}")
                    return ""
                time.sleep(1.0 * (attempt + 1))
    raise TranslateError(
        "Google Dịch đang chặn máy này vì gọi quá nhiều lượt. Đợi vài phút rồi "
        f"thử lại, hoặc chọn engine dịch khác. ({last})"
    )


# ---------------------------------------------------------------- NLLB-200

_nllb_lock = threading.Lock()
_nllb_cache: dict[str, tuple] = {}
NLLB_MODEL = os.environ.get("VSUB_NLLB_MODEL", "facebook/nllb-200-distilled-600M")
NLLB_NO_REPEAT = 4  # một cụm 4 từ lặp lại trong cùng câu thoại gần như luôn là mô hình chạy loạn


def lora_available() -> bool:
    """Có adapter đẳng thời (HP-4) đã huấn luyện và đủ thư viện để nạp hay không.

    Không import torch/peft ở đây — hàm này được gọi cả lúc chỉ dựng bộ siết.
    Tắt hẳn bằng biến môi trường VSUB_NLLB_LORA=0.
    """
    import importlib.util

    from . import isochron
    from ..config import MODEL_DIR

    if os.environ.get("VSUB_NLLB_LORA", "1") == "0" or not isochron.has_adapter(MODEL_DIR):
        return False
    return importlib.util.find_spec("peft") is not None


def lora_applies(source: str | None, target: str | None) -> bool:
    """Adapter chỉ được huấn luyện và đo cho Trung → Việt; cặp khác dùng NLLB gốc."""
    return nllb_code(source or "en") == "zho_Hans" and nllb_code(target or "vi") == "vie_Latn"


def _attach_lora(tok, mdl):
    """Gắn adapter LoRA + 60 token ngân sách `<len:n>` lên NLLB gốc. Trả về (tok, mdl)."""
    import torch
    from peft import PeftModel
    from transformers import AutoTokenizer

    from . import isochron
    from ..config import MODEL_DIR

    path = str(isochron.adapter_dir(MODEL_DIR))
    lora_tok = AutoTokenizer.from_pretrained(path)
    old = mdl.get_input_embeddings().weight.shape[0]
    if len(lora_tok) > old:
        # đúng như lúc huấn luyện (training/train_nllb_lora.py::load_base): hàng mới
        # khởi tạo bằng trung bình, giá trị đã học nằm trong adapter
        mdl.resize_token_embeddings(len(lora_tok), mean_resizing=False)
        with torch.no_grad():
            w = mdl.get_input_embeddings().weight
            w[old:] = w[:old].mean(dim=0, keepdim=True)
    return lora_tok, PeftModel.from_pretrained(mdl, path)


def _load_nllb():
    """Trả về (tokenizer, model, device, có_lora)."""
    import torch
    from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

    from . import hf_cache
    from ..config import MODEL_DIR

    with _nllb_lock:
        if NLLB_MODEL in _nllb_cache:
            return _nllb_cache[NLLB_MODEL]
        try:
            hf_cache.repair(MODEL_DIR)  # cache bị mất symlink -> dựng lại
        except Exception:
            pass
        tok = AutoTokenizer.from_pretrained(NLLB_MODEL, cache_dir=str(MODEL_DIR))
        mdl = AutoModelForSeq2SeqLM.from_pretrained(NLLB_MODEL, cache_dir=str(MODEL_DIR))
        lora = False
        if lora_available() and "nllb-200-distilled-600M" in NLLB_MODEL:
            try:
                tok, mdl = _attach_lora(tok, mdl)
                lora = True
            except Exception:
                # adapter hỏng / lệch phiên bản: nạp lại bản gốc sạch, app vẫn dịch được
                tok = AutoTokenizer.from_pretrained(NLLB_MODEL, cache_dir=str(MODEL_DIR))
                mdl = AutoModelForSeq2SeqLM.from_pretrained(NLLB_MODEL, cache_dir=str(MODEL_DIR))
        device = "cuda" if torch.cuda.is_available() else "cpu"
        mdl = mdl.to(device)
        mdl.eval()
        _nllb_cache[NLLB_MODEL] = (tok, mdl, device, lora)
        return _nllb_cache[NLLB_MODEL]


def _nllb_inputs(texts: list[str], budgets: list | None = None) -> list[str]:
    """Câu đưa vào NLLB: câu rỗng thành "…", gắn token ngân sách nếu có."""
    from . import isochron

    budgets = list(budgets or []) + [None] * len(texts)
    return [isochron.with_budget(t if t.strip() else "…", n) for t, n in zip(texts, budgets)]


def _translate_nllb(texts, source, target, on_progress=None, on_log=None, budgets=None) -> list[str]:
    """Dịch bằng NLLB-200. `budgets[i]` (số âm tiết) chỉ có tác dụng khi adapter đẳng thời
    đang dùng cho cặp ngôn ngữ này; không thì bị bỏ qua."""
    import contextlib

    import torch

    tok, mdl, device, lora = _load_nllb()
    use_lora = lora and lora_applies(source, target)
    if on_log:
        on_log(f"NLLB-200 chạy trên {device.upper()}" + (" · adapter đẳng thời HP-4 (LoRA)" if use_lora else ""))

    src = nllb_code(source or "en")
    tgt = nllb_code(target)
    tok.src_lang = src

    try:
        bos = tok.convert_tokens_to_ids(tgt)
    except Exception:
        bos = None
    if bos is None and hasattr(tok, "lang_code_to_id"):
        bos = tok.lang_code_to_id.get(tgt)
    if bos is None:
        raise TranslateError(f"NLLB không hỗ trợ ngôn ngữ đích: {target}")

    inputs = _nllb_inputs(texts, budgets if use_lora else None)
    # có adapter nhưng cặp ngôn ngữ khác Trung → Việt: tắt adapter, chạy đúng NLLB gốc
    scope = mdl.disable_adapter() if (lora and not use_lora) else contextlib.nullcontext()
    results: list[str] = []
    BATCH = 8
    with scope:
        for i in range(0, len(inputs), BATCH):
            enc = tok(inputs[i : i + BATCH], return_tensors="pt", padding=True, truncation=True, max_length=400)
            enc = {k: v.to(device) for k, v in enc.items()}
            with torch.inference_mode():
                # no_repeat_ngram_size: chặn kiểu chạy loạn "Ồ, Ồ, Ồ, …" (gặp thật khi đo bộ gold)
                gen = mdl.generate(**enc, forced_bos_token_id=bos, max_new_tokens=400, num_beams=4,
                                   no_repeat_ngram_size=NLLB_NO_REPEAT)
            results.extend(tok.batch_decode(gen, skip_special_tokens=True))
            if on_progress:
                on_progress(min(1.0, (i + BATCH) / max(1, len(inputs))))
    return [r.strip() for r in results]


def _nllb_tightener(source: str, target: str, on_log=None):
    """Bộ siết HP-4: dịch lại câu vượt khung với token ngân sách `<len:n>` nhỏ hơn.

    Cần câu gốc (`request["source"]`, do `budget.run_loop` điền). Bản mới chỉ được nhận
    khi thật sự ngắn hơn bản cũ; câu nào không ngắn đi được thì rơi về bộ luật rút gọn.
    """
    from . import duration, shorten

    rules = shorten.make_tightener()

    def tighten(requests: list[dict]) -> list:
        out: list = [r["text"] for r in requests]
        todo = [k for k, r in enumerate(requests) if (r.get("source") or "").strip()]
        if todo:
            if on_log:
                on_log(f"  Dịch lại {len(todo)} câu với token ngân sách <len:n> (NLLB + LoRA đẳng thời).")
            new = _translate_nllb(
                [requests[k]["source"] for k in todo], source, target,
                budgets=[int(requests[k].get("target_syllables") or 1) for k in todo],
            )
            for k, text in zip(todo, new):
                if text and duration.syllables(text) < duration.syllables(requests[k]["text"]):
                    out[k] = text
        rest = [k for k, r in enumerate(requests) if out[k] == r["text"]]
        if rest:
            for k, text in zip(rest, rules([requests[k] for k in rest])):
                out[k] = text
        return out

    return tighten


# ----------------------------------------------- rút gọn có kiểm soát (HP-5)

_TIGHTEN_PROMPT = """Bạn là biên tập viên lồng tiếng {tgt}. Mỗi dòng dưới đây là một câu thoại
ĐANG DÀI HƠN khung thời gian được phép đọc. Hãy viết lại từng câu NGẮN HƠN để đọc kịp.

Định dạng đầu vào: `<số dòng>|<số âm tiết tối đa>|<câu>`.
Quy tắc bắt buộc:
- Câu viết lại KHÔNG được quá số âm tiết tối đa đã cho ở dòng đó.
- Giữ nguyên ý chính, sắc thái, tên riêng và số liệu; bỏ từ đệm, rút gọn cách diễn đạt.
- Không thêm ý mới, không chú thích, không xuống dòng bên trong một câu.
- Trả về ĐÚNG số dòng, mỗi dòng dạng `<số dòng>|<câu đã rút gọn>`, không thêm lời dẫn."""


# Dịch gọn ở bước 4: có câu gốc nên model được DỊCH LẠI cho vừa, không chỉ cắt chữ bản cũ
_FIT_PROMPT = """Bạn là biên dịch viên lồng tiếng {tgt}. Mỗi dòng dưới đây gồm một câu thoại gốc và
bản dịch hiện tại của nó — bản dịch này ĐANG DÀI HƠN khung thời gian của câu. Hãy DỊCH LẠI câu gốc
sang {tgt} sao cho gọn, vừa khung.

Định dạng đầu vào: `<số dòng>|<số âm tiết tối đa>|<câu gốc>|<bản dịch hiện tại>`.
Quy tắc bắt buộc:
- Câu dịch mới KHÔNG được quá số âm tiết tối đa đã cho ở dòng đó.
- Đủ ý của câu gốc; giữ cách xưng hô, tên riêng và giọng điệu của bản dịch hiện tại.
- Là lời nói tự nhiên, trọn câu — chọn cách nói ngắn hơn chứ không cắt cụt câu.
- Không thêm ý mới, không chú thích, không xuống dòng bên trong một câu.
- Trả về ĐÚNG số dòng, mỗi dòng dạng `<số dòng>|<câu dịch mới>`, không thêm lời dẫn."""


# ---------------------------------------------------------- gọi API AI


def ai_timeout() -> float:
    """Thời gian chờ tối đa cho MỘT lượt gọi API AI (giây), đặt qua VSUB_AI_TIMEOUT.

    Mặc định 120 s: đủ cho một lô 40 dòng ở model chậm. Không đặt thì SDK chờ
    600 s và tự thử lại 2 lần; nhân với vòng thử ở đây là cả tiếng cho một
    endpoint treo — người dùng chỉ thấy job "đang chạy" mà không biết vì sao.
    """
    try:
        return max(5.0, float(os.environ.get("VSUB_AI_TIMEOUT", "120")))
    except ValueError:
        return 120.0


def _openai_client(api_key: str, base_url: str = "", timeout: float | None = None, retries: int = 1):
    from openai import OpenAI

    key = api_key or os.environ.get("OPENAI_API_KEY", "")
    if not key:
        raise TranslateError("Chưa có API key: nhập ở bước 2 hoặc đặt biến môi trường OPENAI_API_KEY.")
    args: dict = {"api_key": key}
    if base_url.strip():
        args["base_url"] = base_url.strip().rstrip("/")
    # max_retries: SDK tự thử lại khi lỗi mạng / 429 / 5xx; phần còn lại do _with_retry lo
    return OpenAI(timeout=timeout or ai_timeout(), max_retries=retries, **args)


def _anthropic_client(api_key: str, timeout: float | None = None, retries: int = 1):
    import anthropic

    key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
    if not key:
        raise TranslateError("Chưa có API key: nhập ở bước 2 hoặc đặt biến môi trường ANTHROPIC_API_KEY.")
    return anthropic.Anthropic(api_key=key, timeout=timeout or ai_timeout(), max_retries=retries)


def _short_error(exc: BaseException | None, timeout: float | None = None) -> str:
    """Một dòng dễ hiểu cho lỗi API: nói đúng chuyện gì xảy ra, kèm đuôi thông báo gốc."""
    text = str(exc or "").strip()
    low = text.lower()
    tail = text[:160]
    if "timed out" in low or "timeout" in low:
        return f"Quá {timeout or ai_timeout():.0f}s chưa trả lời (đổi bằng VSUB_AI_TIMEOUT)"
    if "model_not_found" in low or ("404" in low and "model" in low):
        return f"Model không tồn tại ở endpoint này — kiểm tra lại tên model · {tail}"
    if "chưa có api key" in low:
        return text
    if "401" in low or "invalid_api_key" in low or "authentication" in low or "incorrect api key" in low:
        return f"Key sai hoặc hết hạn (401) · {tail}"
    if "429" in low or "rate limit" in low or "insufficient_quota" in low:
        return f"Bị giới hạn tần suất hoặc hết hạn mức (429) · {tail}"
    if "connection" in low or "connect" in low:
        return f"Không kết nối được endpoint — kiểm tra địa chỉ và mạng · {tail}"
    return text[:300]


def _with_retry(call, label: str, on_log=None, attempts: int = 2) -> str:
    """Gọi `call()` tối đa `attempts` lần; ghi log thời gian và lý do từng lượt hỏng."""
    last: Exception | None = None
    for attempt in range(attempts):
        t0 = time.monotonic()
        try:
            return call()
        except TranslateError:
            raise
        except Exception as exc:
            last = exc
            if on_log:
                on_log(f"  Lượt {attempt + 1}/{attempts} lỗi sau {time.monotonic() - t0:.0f}s: {_short_error(exc)}")
            if attempt < attempts - 1:
                time.sleep(2 * (attempt + 1))
    raise TranslateError(f"Lỗi gọi {label}: {_short_error(last)}")


def _call_logged(call, label: str, model: str, index: int, total: int, lines: int, on_log=None) -> str:
    """Một lô dịch: báo trước đang chờ ai, bao lâu tối đa; báo sau mất bao lâu thật."""
    if on_log:
        on_log(f"  Lô {index + 1}/{total}: {lines} câu → chờ {model} (tối đa {ai_timeout():.0f}s mỗi lượt)…")
    t0 = time.monotonic()
    raw = _with_retry(call, label, on_log)
    if on_log:
        on_log(f"  Lô {index + 1}/{total} xong sau {time.monotonic() - t0:.0f}s.")
    return raw


def check_connection(
    engine: str, api_key: str = "", model: str = "", base_url: str = "", timeout: float = 30.0
) -> dict:
    """Gọi thử một câu ngắn để biết key, endpoint và model có dùng được không.

    Trả về dict cho giao diện: ok, latency_ms, reply, model, error. Không ném lỗi:
    dòng lỗi API chính là thứ người dùng cần đọc (key sai, model không có, chậm).
    """
    ok, why = engine_available(engine)
    if not ok:
        return {"ok": False, "error": why, "model": model, "latency_ms": 0, "reply": ""}
    question = "Trả lời đúng một từ: OK"
    t0 = time.monotonic()
    try:
        if engine == "claude":
            model = model or "claude-opus-5"
            resp = _anthropic_client(api_key, timeout=timeout, retries=0).messages.create(
                model=model, max_tokens=16, messages=[{"role": "user", "content": question}]
            )
            reply = "".join(b.text for b in resp.content if b.type == "text")
        elif engine == "openai":
            model = model or "gpt-4o-mini"
            resp = _openai_client(api_key, base_url, timeout=timeout, retries=0).chat.completions.create(
                model=model, messages=[{"role": "user", "content": question}]
            )
            reply = resp.choices[0].message.content or ""
        else:
            return {"ok": False, "error": f"Engine {engine} không cần key, không có gì để kiểm tra.",
                    "model": model, "latency_ms": 0, "reply": ""}
    except Exception as exc:
        return {"ok": False, "error": _short_error(exc, timeout), "model": model,
                "latency_ms": int((time.monotonic() - t0) * 1000), "reply": ""}
    return {"ok": True, "error": "", "model": model,
            "latency_ms": int((time.monotonic() - t0) * 1000), "reply": reply.strip()[:80]}


def _chat(engine: str, system: str, user: str, api_key: str, model: str, base_url: str, on_log=None) -> str:
    """Một lượt hỏi–đáp với Claude hoặc OpenAI, có giới hạn thời gian và thử lại. Trả về text thô."""
    if engine == "claude":
        def call():
            resp = _anthropic_client(api_key).messages.create(
                model=model or "claude-opus-5",
                max_tokens=4000,
                system=system,
                messages=[{"role": "user", "content": user}],
            )
            if resp.stop_reason == "refusal":
                raise TranslateError("Claude từ chối xử lý nội dung này.")
            return "".join(b.text for b in resp.content if b.type == "text")

        return _with_retry(call, "Claude", on_log)

    def call():
        resp = _openai_client(api_key, base_url).chat.completions.create(
            model=model or "gpt-4o-mini",
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        )
        return resp.choices[0].message.content or ""

    return _with_retry(call, "OpenAI", on_log)


def make_tightener(
    engine: str,
    api_key: str = "",
    model: str = "",
    base_url: str = "",
    target: str = "vi",
    on_log: Callable[[str], None] | None = None,
    source: str = "",
    with_source: bool = False,
):
    """Hàm rút gọn có kiểm soát cho `budget.run_loop`, hoặc None nếu engine không hỗ trợ.

    `with_source=True` (nút "Dịch gọn" ở bước 4): engine AI nhận cả câu gốc
    (`request["source"]`) để dịch lại cho vừa thay vì chỉ rút bản dịch cũ.

    Google/MyMemory không điều khiển được độ dài; NLLB thường cũng không — đó là
    việc của mô hình đẳng thời (HP-4) với token ngân sách. Với các engine đó, bản
    dịch tiếng Việt được rút gọn bằng luật (`shorten.py`); ngôn ngữ đích khác thì
    None. Với Claude/OpenAI thì nhắc lại kèm giới hạn âm tiết là cách siết có kiểm soát.

    Câu nào model bỏ sót thì giữ nguyên văn cũ — vòng lặp sẽ thấy nó vẫn vượt và
    tự quyết định thử lượt nữa hay để atempo lo.
    """
    if engine == "nllb" and source and lora_applies(source, target) and lora_available():
        # HP-4: mô hình đẳng thời tự dịch lại ngắn hơn — siết ngay ở khâu dịch thay vì cắt chữ
        return _nllb_tightener(source, target, on_log)
    if engine not in ("claude", "openai"):
        # Google/MyMemory/NLLB không điều khiển được độ dài, nhưng bản dịch tiếng
        # Việt thì rút gọn bằng luật được (bỏ từ đệm, cụm dài → cụm ngắn). Đây là
        # cách duy nhất để cấu hình C0 không có API key cũng bớt phải nén tiếng.
        if (target or "vi").lower().startswith("vi"):
            from . import shorten

            if on_log:
                on_log("  Engine dịch này không điều khiển được độ dài — rút gọn bằng luật tiếng Việt.")
            return shorten.make_tightener(on_log=on_log)
        return None
    system = (_FIT_PROMPT if with_source else _TIGHTEN_PROMPT).format(tgt=name_en(target))
    label = model or ("claude-opus-5" if engine == "claude" else "gpt-4o-mini")

    def flat(text: str) -> str:
        return " ".join((text or "").replace("|", " ").split())

    def tighten(requests: list[dict]) -> list[str]:
        payload = "\n".join(
            f"{i + 1}|{int(r.get('target_syllables') or 1)}|"
            + (f"{flat(r.get('source'))}|{flat(r['text'])}" if with_source else r["text"])
            for i, r in enumerate(requests)
        )
        if on_log:
            on_log(f"  Rút gọn {len(requests)} câu → chờ {label} (tối đa {ai_timeout():.0f}s mỗi lượt)…")
        t0 = time.monotonic()
        raw = _chat(engine, system, payload, api_key, model, base_url)
        if on_log:
            on_log(f"  {label} trả lời sau {time.monotonic() - t0:.0f}s.")
        parsed = _parse_numbered(raw, 0, len(requests))
        return [p if p else r["text"] for p, r in zip(parsed, requests)]

    return tighten


# ------------------------------------------------------------------ Claude

_SYS_PROMPT = """Bạn là biên dịch viên phụ đề và lời thoại lồng tiếng cho phim/video.

Nhiệm vụ: dịch từng dòng thoại từ {src} sang {tgt}.

Định dạng bắt buộc:
- Chỉ dịch các dòng trong phần [CẦN DỊCH]. Trả về ĐÚNG số dòng đó, mỗi dòng dạng `<n>|bản dịch`.
- Không gộp dòng, không tách dòng, không bỏ dòng nào. Dòng nào không cần dịch thì chép lại.
- Phần [ĐÃ DỊCH TRƯỚC ĐÓ] và [CÂU KẾ TIẾP] chỉ để hiểu mạch truyện: không xuất lại, không dịch lại.
- Nếu đầu dòng có tên người nói trong ngoặc tròn, ví dụ `(Nữ 1)`, thì đó là chú thích: KHÔNG chép vào bản dịch.
- Không thêm giải thích, không thêm ngoặc chú thích, không xuống dòng bên trong một dòng, không lời dẫn.

Chất lượng dịch:
- Dịch theo NGỮ CẢNH của cả đoạn hội thoại: ai nói với ai, đang đáp lại câu nào, thái độ ra sao.
  Câu rút gọn, đại từ, câu trả lời cộc lốc phải hiểu theo câu trước đó chứ không dịch rời từng dòng.
- Dịch tự nhiên như người bản xứ nói, không dịch từng chữ. Thành ngữ, tiếng lóng dịch theo nghĩa.
- Chế độ dịch hiện tại: {mode}.
- Giữ số từ gần bản gốc nhất có thể, thường trong khoảng 75–125% số từ gốc.
    Không thêm ý giải thích. Nếu bản dịch dài, hãy chủ động rút gọn mà vẫn giữ ý chính.
- Với chế độ tối ưu lồng tiếng, ưu tiên câu ngắn, dễ nói và vừa thời lượng cue hơn dịch sát từng chữ.
- Giữ nguyên thương hiệu, số liệu, đơn vị. {names}
- Một tên riêng, một thuật ngữ, một cặp xưng hô đã dùng ở phần trước thì dùng lại y như vậy.{pronouns}{note}{cast}{brief}{glossary}{examples}"""

_PRONOUN_RULE = """
- Xưng hô tiếng Việt: chọn theo giới, tuổi, vai vế và quan hệ giữa người nói với người nghe
  (anh/chị/em, cô/chú/bác, con/cháu, ông/bà, mày/tao; phim cổ trang: ta/ngươi, chàng/nàng/thiếp, huynh/đệ/muội…).
  KHÔNG dùng "bạn" trừ khi hai người thật sự là bạn bè hoặc đang nói với khán giả.
  Mỗi cặp nhân vật giữ MỘT cặp xưng hô suốt phim, chỉ đổi khi quan hệ đổi."""

_BRIEF_PROMPT = """Bạn đọc lướt kịch bản phụ đề ({src}) của một video để chuẩn bị cho người dịch sang {tgt}.
Viết một bản ghi chú NGẮN (tối đa 220 từ, viết bằng tiếng Việt), gồm đúng các mục:
1. Thể loại, bối cảnh, giọng văn nên dùng (1–2 câu).
2. Tóm tắt nội dung (2–3 câu).
3. Nhân vật: tên (kèm cách viết ở ngôn ngữ đích), giới, vai vế, quan hệ với nhau.
4. Xưng hô đề nghị cho từng cặp nhân vật chính (ai gọi ai là gì, tự xưng là gì).
5. Tên riêng, địa danh, thuật ngữ lặp lại: `nguyên văn = cách dịch`.
Chỉ ghi điều suy ra được từ kịch bản; không chắc thì bỏ qua, không bịa. Không lời dẫn."""

# Số câu đã dịch / sắp tới đưa kèm mỗi lô để model nắm mạch hội thoại
CONTEXT_BEFORE = 8
CONTEXT_AFTER = 4
# Kịch bản ngắn hơn ngần này câu thì một lô đã thấy trọn, khỏi đọc lướt trước
BRIEF_MIN_LINES = 12
BRIEF_MAX_CHARS = 9000


def _names_rule(source: str | None, target: str) -> str:
    src = (source or "").lower()
    if (target or "").lower().startswith("vi") and src.startswith(("zh", "yue")):
        return "Tên người, địa danh tiếng Trung chuyển sang âm Hán-Việt (không để pinyin)."
    return "Giữ nguyên tên riêng theo cách viết quen thuộc ở ngôn ngữ đích."


_GLOSS_SEP = re.compile(r"\s*(?:=>|->|→|=|：|:)\s*")


def parse_glossary(text: str) -> list[tuple[str, str]]:
    """Đọc bộ thuật ngữ `nguồn = đích` (nhận cả `->`, `:`; `a / b = c` là hai cách viết nguồn).

    Trả về mục dài trước, để "朱大生" được thay trước "朱"."""
    pairs: list[tuple[str, str]] = []
    for line in (text or "").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = _GLOSS_SEP.split(line, maxsplit=1)
        if len(parts) != 2 or not parts[0].strip() or not parts[1].strip():
            continue
        for src in re.split(r"\s*/\s*", parts[0].strip()):
            if src:
                pairs.append((src, parts[1].strip()))
    pairs.sort(key=lambda p: -len(p[0]))
    return pairs


def apply_glossary(texts: list[str], pairs: list[tuple[str, str]]) -> tuple[list[str], int]:
    """Thay thuật ngữ nguồn bằng cách dịch đã định ngay trong câu gốc. Trả về (câu, số câu có thay).

    Google/NLLB không nhận chỉ dẫn, nhưng chữ Latinh nằm sẵn trong câu thì chúng để nguyên
    (đo thật zh→vi: "朱大生" ra "Zhu Dasheng", thay sẵn thì ra "Chu Đại Sinh"; "奴家" ra
    "gia đình nô lệ", thay sẵn thì hết). Từ chữ Latinh chỉ thay khi đứng trọn từ.
    """
    if not pairs:
        return list(texts), 0
    out, used = [], 0
    for text in texts:
        new = text
        for src, tgt in pairs:
            if _CJK.search(src):
                if src in new:
                    new = new.replace(src, f" {tgt} ")
            else:
                new = re.sub(rf"(?<!\w){re.escape(src)}(?!\w)", lambda _m, t=tgt: t, new, flags=re.IGNORECASE)
        if new != text:
            used += 1
            new = re.sub(r"[ \t]{2,}", " ", new).strip()
        out.append(new)
    return out, used


def _cast_label(person: dict) -> str:
    return (person.get("name") or person.get("id") or "").strip()


def _speaker_labels(cues: list[Cue], groups: list[list[int]], cast: list[dict] | None) -> list[str] | None:
    """Tên người nói của từng câu gửi đi dịch, hoặc None nếu phụ đề chưa gán vai."""
    names = {str(p.get("id") or ""): _cast_label(p) for p in (cast or [])}
    labels = []
    for g in groups:
        sid = (cues[g[0]].speaker or "").strip()
        labels.append(names.get(sid) or sid)
    return labels if any(labels) else None


def _cast_note(cast: list[dict] | None, speakers: list[str] | None) -> str:
    if not cast or not speakers:
        return ""
    gender = {"M": "nam", "F": "nữ"}
    age = {"C": "trẻ em", "A": "người lớn", "E": "cao tuổi"}
    present = set(speakers)
    rows = []
    for p in cast:
        label = _cast_label(p)
        if not label or label not in present:
            continue
        facts = [x for x in (gender.get(p.get("gender") or ""), age.get(p.get("age") or "")) if x]
        rows.append(f"  {label}: {', '.join(facts) if facts else 'chưa rõ'}")
    if not rows:
        return ""
    return ("\n- Người nói (máy nghe giọng mà đoán, có thể nhầm — lời thoại mâu thuẫn thì tin lời thoại):\n"
            + "\n".join(rows))


def _recall(texts: list[str], source, target, on_log=None) -> tuple[dict[int, str], list[tuple[str, str]]]:
    """Tra bộ nhớ dịch: (câu trùng khớp -> bản đã duyệt, vài cặp gần giống làm mẫu cho AI)."""
    try:
        from ..store import memory

        exact, examples = memory.lookup(texts, source, target)
    except Exception:  # bộ nhớ dịch hỏng không được làm hỏng việc dịch
        return {}, []
    if exact and on_log:
        on_log(f"Bộ nhớ dịch: {len(exact)} câu dùng lại bản bạn đã sửa tay trước đây.")
    return exact, examples


def _story_brief(engine, texts, source, target, api_key, model, base_url, on_log=None) -> str:
    """Cho model đọc lướt cả kịch bản một lượt, trả về ghi chú nhân vật / xưng hô / tên riêng.

    Dịch theo lô 40 câu thì lô sau không biết lô trước gọi nhân vật là gì; ghi chú này
    đi kèm MỌI lô nên tên và xưng hô thống nhất từ đầu tới cuối. Lỗi thì bỏ qua, dịch tiếp.
    """
    lines = [t.strip() for t in texts if t.strip()]
    if len(lines) < BRIEF_MIN_LINES:
        return ""
    script = "\n".join(lines)
    if len(script) > BRIEF_MAX_CHARS:
        # Kịch bản dài: lấy đầu, giữa, cuối — nhân vật và quan hệ lộ ra ở cả ba chỗ
        third = BRIEF_MAX_CHARS // 3
        mid = len(script) // 2
        script = "\n[…]\n".join([script[:third], script[mid - third // 2: mid + third // 2], script[-third:]])
    system = _BRIEF_PROMPT.format(src=name_en(source), tgt=name_en(target))
    if on_log:
        on_log("Đọc lướt kịch bản để nắm nhân vật, xưng hô và tên riêng trước khi dịch…")
    try:
        brief = (_chat(engine, system, script, api_key, model, base_url) or "").strip()
    except Exception as exc:
        if on_log:
            on_log(f"  Không đọc lướt được ({_short_error(exc)}) — dịch tiếp không có ghi chú tự động.")
        return ""
    # Một dòng "OK" hay câu từ chối không phải ghi chú
    if len(brief) < 40:
        return ""
    return brief[:2400]


def _batch_payload(texts, results, batch, speakers) -> str:
    """Nội dung gửi cho một lô: vài câu đã dịch ngay trước, các câu cần dịch, vài câu kế tiếp."""
    first, last = batch[0], batch[-1]

    def said(i: int) -> str:
        who = (speakers[i] if speakers else "") or ""
        text = texts[i] if texts[i].strip() else "…"
        # `|` trong lời thoại sẽ làm lệch định dạng `<n>|…`
        text = text.replace("|", "/")
        return f"({who}) {text}" if who else text

    parts = []
    before = [i for i in range(max(0, first - CONTEXT_BEFORE), first) if texts[i].strip() and results[i]]
    if before:
        parts.append("[ĐÃ DỊCH TRƯỚC ĐÓ]\n" + "\n".join(
            f"- {said(i)} → {results[i].replace('|', '/')}" for i in before))
    body = "\n".join(f"{i + 1}|{said(i)}" for i in batch)
    after = [i for i in range(last + 1, min(len(texts), last + 1 + CONTEXT_AFTER)) if texts[i].strip()]
    if not before and not after:
        return body
    parts.append("[CẦN DỊCH]\n" + body)
    if after:
        parts.append("[CÂU KẾ TIẾP]\n" + "\n".join(f"- {said(i)}" for i in after))
    return "\n\n".join(parts)


def _strip_speaker_tag(text: str, who: str) -> str:
    """Model đôi khi chép luôn `(Nữ 1)` vào bản dịch — bỏ đi, nếu không TTS sẽ đọc cả tên vai."""
    if who and text.startswith(f"({who})"):
        return text[len(who) + 2:].lstrip(" :-")
    return text


def _numbered(texts: list[str], offset: int) -> str:
    return "\n".join(f"{offset + i + 1}|{t if t.strip() else '…'}" for i, t in enumerate(texts))


def _parse_numbered(raw: str, offset: int, count: int) -> list[str]:
    """Đọc kết quả AI trả về theo dạng `số | nội dung`.

    Gán theo ĐÚNG số dòng model trả về chứ không theo thứ tự, nên model bỏ sót
    hay đảo dòng thì bản dịch vẫn vào đúng cue. Dòng nào model không trả về thì
    để rỗng — bên gọi tự quyết định thay bằng gì.
    """
    out = [""] * count
    for line in (raw or "").splitlines():
        line = line.strip()
        if not line:
            continue
        m = re.match(r"^\s*(\d+)\s*[|｜:.\)]\s?(.*)$", line)
        if not m:
            continue
        idx = int(m.group(1)) - offset - 1
        if 0 <= idx < count:
            out[idx] = m.group(2).strip()
    return out


def _apply_parsed(results: list[str], batch: list[int], texts: list[str], parsed: list[str]) -> int:
    """Ghi kết quả đã đọc vào `results`. Trả về số dòng AI bỏ sót.

    Dòng bị bỏ sót thì giữ nguyên văn gốc — thà để nguyên chữ gốc còn hơn mất
    dòng, nhưng phải đếm lại để nói cho người dùng biết, không thì phụ đề lẫn
    chữ nước ngoài mà chẳng ai hay.
    """
    missing = 0
    for i, val in zip(batch, parsed):
        if val:
            results[i] = val
        else:
            results[i] = texts[i]
            if texts[i].strip():
                missing += 1
    return missing


def _warn_missing(missing: int, total: int, engine: str, on_log) -> None:
    if missing and on_log:
        on_log(
            f"⚠ {engine} không trả về bản dịch cho {missing}/{total} câu — "
            "những câu đó đang giữ nguyên văn gốc. Sửa tay ở bước 4, "
            "hoặc dịch lại bằng Google."
        )


def _ai_batches(texts: list[str], max_chars: int = 2600, max_lines: int = 40):
    cur: list[int] = []
    cur_len = 0
    for i, t in enumerate(texts):
        if cur and (cur_len + len(t) > max_chars or len(cur) >= max_lines):
            yield cur
            cur, cur_len = [], 0
        cur.append(i)
        cur_len += len(t) + 6
    if cur:
        yield cur


def _mode_label(mode: str) -> str:
    return {
        "natural": "tự nhiên, sát ý",
        "funny": "hài hước, bắt trend nhưng không làm sai nội dung",
        "cinematic": "điện ảnh, giàu cảm xúc",
        "dubbing": "tối ưu lồng tiếng, ngắn gọn và dễ đọc thành tiếng",
    }.get(mode, "tự nhiên, sát ý")


def _length_units(text: str) -> int:
    """Đếm đơn vị đọc ổn định hơn `split()` cho cả ngôn ngữ không cách chữ."""
    if _CJK.search(text or ""):
        return max(1, len(re.sub(r"\s+", "", text or "")))
    return max(1, len(re.findall(r"\S+", text or "")))


def _warn_long_translations(
    source_texts: list[str], translated_texts: list[str], mode: str, on_log=None
) -> None:
    """Cảnh báo câu dịch vượt độ dài hợp lý trước khi chuyển sang TTS."""
    if not on_log:
        return
    limit = 1.25
    long_count = sum(
        bool(src.strip()) and _length_units(tr) > _length_units(src) * limit
        for src, tr in zip(source_texts, translated_texts)
    )
    if long_count:
        suffix = " — nên rút gọn ở bước 4 trước khi lồng tiếng" if mode == "dubbing" else ""
        on_log(
            f"⚠ {long_count} câu dịch dài hơn 125% bản gốc{suffix}. "
            "Kiểm tra và rút gọn các dòng dài ở bước 4 khi cần."
        )


def _translate_ai(engine, texts, source, target, api_key, model, base_url, note, mode, glossary,
                  on_progress=None, on_log=None, speakers=None, cast=None, auto_context=True, examples=None):
    """Dịch bằng Claude hoặc endpoint kiểu OpenAI, theo lô, mỗi lô mang theo ngữ cảnh quanh nó."""
    label = "Claude" if engine == "claude" else "OpenAI"
    model = model or ("claude-opus-5" if engine == "claude" else "gpt-4o-mini")
    if on_log:
        on_log(f"Dịch bằng {label} ({model})")

    brief = _story_brief(engine, texts, source, target, api_key, model, base_url, on_log) if auto_context else ""
    is_vi = (target or "").lower().startswith("vi")
    system = _SYS_PROMPT.format(
        src=name_en(source), tgt=name_en(target),
        mode=_mode_label(mode),
        names=_names_rule(source, target),
        pronouns=_PRONOUN_RULE if is_vi else "",
        note=f"\n- Bối cảnh video (người dùng ghi): {note.strip()}" if note.strip() else "",
        cast=_cast_note(cast, speakers),
        brief=f"\n- Ghi chú đọc lướt kịch bản (tự động; bối cảnh người dùng ghi thì ưu tiên hơn):\n{brief}" if brief else "",
        glossary=f"\n- Bộ thuật ngữ bắt buộc áp dụng nhất quán:\n{glossary.strip()}" if glossary.strip() else "",
        examples=("\n- Những câu người dùng đã duyệt ở dự án trước — theo đúng cách dịch và xưng hô này:\n"
                  + "\n".join(f"  {a} → {b}" for a, b in examples)) if examples else "",
    )

    if engine == "claude":
        client = _anthropic_client(api_key)

        def ask(payload: str) -> str:
            resp = client.messages.create(
                model=model,
                max_tokens=8000,
                system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
                messages=[{"role": "user", "content": payload}],
            )
            if resp.stop_reason == "refusal":
                raise TranslateError("Claude từ chối xử lý nội dung này.")
            return "".join(b.text for b in resp.content if b.type == "text")
    else:
        client = _openai_client(api_key, base_url)

        def ask(payload: str) -> str:
            resp = client.chat.completions.create(
                model=model,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": payload}],
            )
            return resp.choices[0].message.content or ""

    results = [""] * len(texts)
    missing = 0
    batches = list(_ai_batches(texts))
    for bi, batch in enumerate(batches):
        payload = _batch_payload(texts, results, batch, speakers)
        raw = _call_logged(lambda payload=payload: ask(payload), label, model, bi, len(batches), len(batch), on_log)
        parsed = _parse_numbered(raw, batch[0], len(batch))
        if speakers:
            parsed = [_strip_speaker_tag(p, speakers[i]) for p, i in zip(parsed, batch)]
        missing += _apply_parsed(results, batch, texts, parsed)
        if on_progress:
            on_progress((bi + 1) / len(batches))

    _warn_missing(missing, len(texts), label, on_log)
    return results


def _translate_claude(texts, source, target, api_key, model, note, mode, glossary, on_progress=None, on_log=None):
    return _translate_ai("claude", texts, source, target, api_key, model, "", note, mode, glossary, on_progress, on_log)


def _translate_openai(texts, source, target, api_key, model, base_url, note, mode, glossary, on_progress=None, on_log=None):
    return _translate_ai("openai", texts, source, target, api_key, model, base_url, note, mode, glossary, on_progress, on_log)
