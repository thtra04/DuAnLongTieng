"""Nhân vật của một dự án và giọng gán cho từng vai — bảng characters/voices.

Nối ba hợp phần của đề cương: phân đoạn người nói (HP-1) sinh ra nhãn S1, S2…;
bảng ánh xạ nhân vật → giọng (HP-2) do người dùng chọn; cơ sở dữ liệu quan hệ
(HP-7) giữ chúng lại qua các lần mở dự án.

    sync()           — sau bước phân đoạn: ghi nhãn + tổng giây nói, giữ tên/giọng đã đặt
    update()         — người dùng đổi tên vai hoặc chọn giọng ở bước 4
    record_voices()  — lúc xuất lồng tiếng: ghi giọng thực sự đã dùng (kể cả mẫu nhân bản)
    list_for()       — trả về cho giao diện khi mở lại dự án
"""

from __future__ import annotations

import re

from ..db import Character, Voice, get_db

LABEL_RE = re.compile(r"^[A-Za-z0-9_-]{1,16}$")
MAX_NAME = 40  # khớp maxlength ô nhập tên vai ở giao diện
DEFAULT_STYLE = "tu_nhien"


class CharacterError(ValueError):
    pass


def _check_label(label) -> str:
    label = str(label or "").strip()
    if not LABEL_RE.match(label):
        raise CharacterError("Nhãn nhân vật không hợp lệ.")
    return label


def _check_gender(gender) -> str:
    g = str(gender or "").strip().upper()[:1]
    return g if g in ("M", "F") else ""


def _check_job(job_id) -> str:
    job_id = str(job_id or "").strip()
    if not job_id:
        raise CharacterError("Thiếu id dự án.")
    return job_id


def _to_dict(ch: Character) -> dict:
    v = ch.voice
    return {
        "label": ch.speaker_label,
        "name": ch.name or "",
        "seconds": round(ch.total_speech or 0.0, 1),
        "gender": ch.gender or "",
        "f0": round(ch.f0 or 0.0, 1),
        "voice": v.voice_id if v else "",
        "style": v.style if v else "",
        "ref_path": (v.ref_path or "") if v else "",
    }


def _rows(db, job_id: str) -> list[Character]:
    rows = db.query(Character).filter_by(job_id=job_id).all()
    rows.sort(key=lambda c: (-(c.total_speech or 0.0), c.speaker_label))
    return rows


def _get_or_create(db, job_id: str, label: str) -> Character:
    ch = db.query(Character).filter_by(job_id=job_id, speaker_label=label).first()
    if ch is None:
        ch = Character(job_id=job_id, speaker_label=label, name="", total_speech=0.0)
        db.add(ch)
    return ch


def _set_voice(ch: Character, voice: str, style: str | None = None, ref_path: str | None = None) -> None:
    voice = str(voice or "").strip()[:64]
    if not voice:
        ch.voice = None  # delete-orphan: dòng voices bị xoá lúc flush
        return
    if ch.voice is None:
        ch.voice = Voice(voice_id=voice, style=DEFAULT_STYLE)
    else:
        ch.voice.voice_id = voice
    if style is not None:
        ch.voice.style = str(style).strip()[:32] or DEFAULT_STYLE
    if ref_path is not None:
        ch.voice.ref_path = str(ref_path) or None


# ------------------------------------------------------------------ public


def list_for(job_id) -> list[dict]:
    job_id = str(job_id or "").strip()
    if not job_id:
        return []
    with get_db() as db:
        return [_to_dict(c) for c in _rows(db, job_id)]


def sync(job_id, speakers: list[dict] | None) -> list[dict]:
    """Ghi/cập nhật vai theo kết quả phân đoạn.

    Giữ tên và giọng người dùng đã đặt cho nhãn còn tồn tại; nhãn không còn
    xuất hiện thì bỏ. Nhãn không hợp lệ bị bỏ qua chứ không làm hỏng cả bước.
    """
    job_id = str(job_id or "").strip()
    if not job_id:
        return []
    wanted: dict[str, dict] = {}
    for s in speakers or []:
        if not isinstance(s, dict):
            continue
        try:
            label = _check_label(s.get("id"))
        except CharacterError:
            continue
        wanted[label] = {
            "seconds": float(s.get("seconds") or 0.0),
            "gender": _check_gender(s.get("gender")),
            "f0": max(0.0, float(s.get("f0") or 0.0)),
            # Tên gợi ý (vd. "Nam" / "Nữ") chỉ dùng khi vai mới được tạo
            "name": " ".join(str(s.get("name") or "").split())[:MAX_NAME],
        }

    with get_db() as db:
        existing = {c.speaker_label: c for c in _rows(db, job_id)}
        for label, info in wanted.items():
            ch = existing.get(label)
            if ch is None:
                db.add(Character(
                    job_id=job_id, speaker_label=label, name=info["name"],
                    total_speech=info["seconds"], gender=info["gender"], f0=info["f0"],
                ))
            else:
                ch.total_speech = info["seconds"]
                if info["gender"]:
                    ch.gender = info["gender"]
                if info["f0"]:
                    ch.f0 = info["f0"]
        for label, ch in existing.items():
            if label not in wanted:
                db.delete(ch)
        db.flush()
        return [_to_dict(c) for c in _rows(db, job_id)]


def update(
    job_id, label, name: str | None = None, voice: str | None = None,
    style: str | None = None, gender: str | None = None,
) -> dict:
    """Người dùng sửa một vai. Vai chưa có trong DB (nhãn tự đặt ở bước 4) thì tạo mới.

    `voice=""` gỡ giọng đã chọn. `style` chỉ có nghĩa khi vai đang có giọng.
    """
    job_id = _check_job(job_id)
    label = _check_label(label)
    with get_db() as db:
        ch = _get_or_create(db, job_id, label)
        if name is not None:
            ch.name = " ".join(str(name).split())[:MAX_NAME]
        if gender is not None:
            ch.gender = _check_gender(gender)
        if voice is not None:
            _set_voice(ch, voice, style=style)
        elif style is not None and ch.voice is not None:
            ch.voice.style = str(style).strip()[:32] or DEFAULT_STYLE
        db.flush()
        return _to_dict(ch)


def record_voices(
    job_id,
    present,
    voice_map: dict | None,
    ref_map: dict | None,
    default_voice: str,
    style: str,
    clone_id: str = "__clone__",
) -> list[dict]:
    """Sau khi xuất lồng tiếng: ghi giọng thực dùng cho từng vai có trong phụ đề.

    Vai có mẫu cắt từ video (`ref_map`) là giọng nhân bản; vai trong `voice_map`
    dùng giọng dựng sẵn đã chọn (hoặc giọng thay thế khi không cắt được mẫu);
    còn lại dùng giọng chung `default_voice`.
    """
    job_id = str(job_id or "").strip()
    if not job_id:
        return []
    voice_map = voice_map or {}
    ref_map = ref_map or {}
    with get_db() as db:
        for raw in present or []:
            try:
                label = _check_label(raw)
            except CharacterError:
                continue
            ref = str(ref_map.get(label) or "")
            voice = str(voice_map.get(label) or "") or (clone_id if ref else default_voice)
            ch = _get_or_create(db, job_id, label)
            _set_voice(ch, voice, style=style, ref_path=ref)
        db.flush()
        return [_to_dict(c) for c in _rows(db, job_id)]


def delete_for(job_id) -> int:
    """Xoá mọi vai (và giọng) của một dự án. Trả về số vai đã xoá."""
    job_id = str(job_id or "").strip()
    if not job_id:
        return 0
    with get_db() as db:
        rows = db.query(Character).filter_by(job_id=job_id).all()
        for ch in rows:
            db.delete(ch)
        return len(rows)
