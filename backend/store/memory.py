"""Bộ nhớ dịch — tool học từ những câu người dùng đã sửa tay.

Mỗi lần xuất, bản dịch người dùng gửi lên được so với bản máy dịch lưu trong
`state.json`. Câu nào khác tức là người dùng đã sửa: cặp (câu gốc → bản đã sửa)
được ghi lại. Lần dịch sau:

    * câu gốc trùng khớp  → dùng lại bản đã sửa, engine nào cũng vậy;
    * câu gần giống       → đưa cho engine AI làm mẫu về cách dịch và xưng hô.

Đây cũng là nguồn dữ liệu song ngữ đã qua tay người cho việc tinh chỉnh mô hình
dịch (HP-4/HP-6): `export_jsonl()` xuất đúng định dạng notebook 03 đọc.

    learn_from_edit()  — gọi ở API xuất, trước khi ghi đè state.json
    lookup()           — gọi ở translate.translate_cues
    export_jsonl()     — xuất corpus huấn luyện
"""

from __future__ import annotations

import json
import re
import time
import unicodedata
from pathlib import Path

from ..db import Base, TranslationMemory, _get_engine, get_db

# Chỉ tra ngần này cặp mới nhất: đủ cho vài trăm tập phim mà vẫn tức thì
MAX_ROWS = 5000
MAX_EXAMPLES = 8
# Một cặp được coi là "gần giống kịch bản đang dịch" khi ít nhất ngần này phần
# bộ ba ký tự của câu gốc xuất hiện trong kịch bản
MIN_OVERLAP = 0.5
MAX_LEN = 400

_ready = False
_TRAILING = " \t.,!?;:…。，！？；：、~-—\"'”’)]}»"


def _ensure_table() -> None:
    """Luồng xử lý job có thể chạy trước khi app kịp `init_db()` (test, script đo)."""
    global _ready
    if not _ready:
        Base.metadata.create_all(_get_engine(), tables=[TranslationMemory.__table__])
        _ready = True


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFC", text or "").lower()
    text = re.sub(r"\s+", " ", text).strip()
    return text.rstrip(_TRAILING).strip()[:MAX_LEN]


def _lang(code) -> str:
    return (code or "").lower().split("-")[0][:12]


def _trigrams(text: str) -> set[str]:
    text = re.sub(r"\s+", "", normalize(text))
    if len(text) < 3:
        return {text} if text else set()
    return {text[i:i + 3] for i in range(len(text) - 2)}


def learn(pairs: list[tuple[str, str]], source_lang: str = "", target_lang: str = "",
          job_id: str = "") -> int:
    """Ghi các cặp (gốc, bản dịch đã duyệt). Câu gốc đã có thì cập nhật bản dịch. Trả về số cặp ghi."""
    _ensure_table()
    tgt = _lang(target_lang)
    saved = 0
    now = time.time()
    with get_db() as db:
        for source, target in pairs:
            source, target = (source or "").strip(), (target or "").strip()
            key = normalize(source)
            if not key or not target or len(source) > MAX_LEN or len(target) > MAX_LEN * 2:
                continue
            row = (
                db.query(TranslationMemory)
                .filter(TranslationMemory.source_key == key, TranslationMemory.target_lang == tgt)
                .first()
            )
            if row is None:
                db.add(TranslationMemory(
                    source_key=key, source=source, target=target, source_lang=_lang(source_lang),
                    target_lang=tgt, job_id=str(job_id or "")[:32], hits=0, updated=now,
                ))
            elif row.target != target:
                row.target, row.updated, row.job_id = target, now, str(job_id or "")[:32]
            else:
                continue
            saved += 1
    return saved


def lookup(texts: list[str], source_lang: str | None, target_lang: str) -> tuple[dict[int, str], list[tuple[str, str]]]:
    """Tra bộ nhớ cho một kịch bản.

    Trả về ``(chỉ số câu -> bản dịch đã duyệt, [(gốc, dịch)] gần giống để làm mẫu)``.
    """
    _ensure_table()
    tgt = _lang(target_lang)
    with get_db() as db:
        rows = (
            db.query(TranslationMemory)
            .filter(TranslationMemory.target_lang == tgt)
            .order_by(TranslationMemory.updated.desc())
            .limit(MAX_ROWS)
            .all()
        )
        if not rows:
            return {}, []
        by_key = {}
        for r in rows:  # mới nhất trước -> giữ bản mới nhất
            by_key.setdefault(r.source_key, r)

        exact: dict[int, str] = {}
        used_ids = set()
        for i, text in enumerate(texts):
            row = by_key.get(normalize(text))
            if row is not None and text.strip():
                exact[i] = row.target
                used_ids.add(row.id)
        if used_ids:
            db.query(TranslationMemory).filter(TranslationMemory.id.in_(used_ids)).update(
                {TranslationMemory.hits: TranslationMemory.hits + 1}, synchronize_session=False
            )

        script: set[str] = set()
        for text in texts:
            script |= _trigrams(text)
        scored = []
        for r in by_key.values():
            if r.id in used_ids:
                continue
            grams = _trigrams(r.source)
            if len(grams) < 2:
                continue
            overlap = len(grams & script) / len(grams)
            if overlap >= MIN_OVERLAP:
                scored.append((overlap, r.updated, r.source, r.target))
        scored.sort(reverse=True)
        examples = [(s, t) for _o, _u, s, t in scored[:MAX_EXAMPLES]]
    return exact, examples


def learn_from_edit(old_cues: list[dict], new_cues: list[dict], source_lang: str = "",
                    target_lang: str = "", job_id: str = "") -> int:
    """So bản dịch người dùng gửi lên với bản máy dịch đã lưu; câu nào khác thì ghi nhớ.

    So theo **câu** (nhóm cue như lúc dịch) chứ không theo dòng: lúc dịch, một câu
    vắt qua nhiều cue được dịch trọn rồi chia lại, nên phải nối lại mới ra đúng
    đơn vị mà lần dịch sau sẽ tra. Người dùng tách/gộp/sửa chữ gốc thì dòng không
    còn đối chiếu được — bỏ qua, không đoán.
    """
    if not old_cues or len(old_cues) != len(new_cues):
        return 0
    from ..core.subtitles import Cue
    from ..core.translate import _join_fragments, group_cues

    old = [Cue.from_dict(c) for c in old_cues]
    new = [Cue.from_dict(c) for c in new_cues]
    if any(a.text != b.text for a, b in zip(old, new)):
        return 0
    pairs = []
    for g in group_cues(new, split_cjk_lines=True):
        source = _join_fragments([new[i].text for i in g])
        before = _join_fragments([old[i].text2 for i in g])
        after = _join_fragments([new[i].text2 for i in g])
        if source.strip() and after.strip() and after != before:
            pairs.append((source, after))
    return learn(pairs, source_lang, target_lang, job_id) if pairs else 0


def stats() -> dict:
    _ensure_table()
    with get_db() as db:
        q = db.query(TranslationMemory)
        return {"pairs": q.count(), "reused": sum(r.hits or 0 for r in q.all())}


def clear() -> int:
    _ensure_table()
    with get_db() as db:
        return db.query(TranslationMemory).delete()


def export_jsonl(path: Path, target_lang: str = "") -> int:
    """Xuất bộ nhớ thành corpus song ngữ JSONL: {"src", "tgt", "src_lang", "tgt_lang"}."""
    _ensure_table()
    with get_db() as db:
        q = db.query(TranslationMemory)
        if target_lang:
            q = q.filter(TranslationMemory.target_lang == _lang(target_lang))
        rows = [
            {"src": r.source, "tgt": r.target, "src_lang": r.source_lang, "tgt_lang": r.target_lang}
            for r in q.order_by(TranslationMemory.id).all()
        ]
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return len(rows)
