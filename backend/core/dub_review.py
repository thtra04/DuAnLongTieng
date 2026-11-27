"""Prepare a reading draft, then bind its approved words to the original timed cues."""

import hashlib
import json
import re
import unicodedata
from dataclasses import replace

from pydantic import BaseModel, Field

from . import budget, dubbing, translate
from .subtitles import is_cjk


def _translated(cues, source, target):
    language = (source or "").lower().split("-")[0]
    return bool(target or any(c.text2 for c in cues) or language not in ("", "vi", "auto", "und") or
                is_cjk("".join(c.text for c in cues[:60])))


class ReadingMix(BaseModel):
    voice: str = Field(default="", max_length=128)
    style: str = Field(default="tu_nhien", max_length=32)
    voices: dict[str, str] = Field(default_factory=dict, max_length=20000)
    max_speed: float = Field(default=1.5, ge=1, le=2, allow_inf_nan=False)
    offset: float = Field(default=0, allow_inf_nan=False)


def playback(settings, cues):
    mix = ReadingMix.model_validate(settings).model_dump()
    mix["voices"] = {s: mix["voices"].get(s) or mix["voice"] for s in dubbing.speaker_ids(cues)}
    return mix


def _foreign_letters(text):
    return any(ch.isalpha() and not unicodedata.name(ch, "").startswith("LATIN") for ch in text)


def _issues(cues, translated):
    result = []
    for i, c in enumerate(cues):
        text = c.text2 if translated else c.text
        if not text.strip():
            reason = "Thiếu bản dịch" if translated else "Thiếu lời thoại"
        elif _foreign_letters(text):
            reason = "Còn chữ chưa dịch sang tiếng Việt"
        elif not dubbing._clean_for_tts(text, add_stop=False):
            reason = "Không có chữ đọc được"
        elif i + 1 < len(cues) and cues[i + 1].start == c.start:
            result.append({"cue": i, "reason": f"Trùng mốc bắt đầu với dòng #{i + 2}", "field": "start"})
            continue
        else:
            continue
        result.append({"cue": i, "reason": reason})
    return result


def _revision(cues, groups, project, source, target, shorten):
    data = [project or "", source or "", target or "", bool(shorten), [c.to_dict() for c in cues], groups]
    return hashlib.sha256(json.dumps(data, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()


def draft(cues, project="", source="", target="", shorten=False):
    translated = _translated(cues, source, target)
    # Reviewing a project pins each utterance to its own subtitle, including in the
    # timing budget. The standalone phrase builder can still join sentence fragments.
    spoken = [replace(c, pinned=True) for c in cues] if project else [replace(c) for c in cues]
    if translated and shorten and (target or "vi").lower().startswith("vi"):
        budget.run_loop(spoken, translate.spoken_tightener())
    units = dubbing.speech_units(spoken, translated)
    if project and len(units) != len(cues):
        by_cue = {u["cues"][0]: u for u in units}
        units = [by_cue.get(i) or {"cues": [i], "start": c.start, "end": c.end,
                                  "speaker": c.speaker, "text": ""} for i, c in enumerate(cues)]
    groups = [u["cues"] for u in units]
    return {"units": units, "use_translation": translated, "issues": _issues(cues, translated),
            "revision": _revision(cues, groups, project, source, target, shorten)}


def reading_unit(cues, row):
    """Use only the text and cue indices from the editor, never client paths, speakers or times."""
    ids = row.get("cues") if isinstance(row, dict) else None
    if not isinstance(ids, list) or len(ids) != 1 or type(ids[0]) is not int or not 0 <= ids[0] < len(cues):
        raise ValueError("Mỗi dòng phụ đề cần đúng một câu đọc. Hãy dựng lại kịch bản.")
    text = row.get("text")
    if (not isinstance(text, str) or not text.strip() or _foreign_letters(text) or
            dubbing._clean_for_tts(text, add_stop=False) != " ".join(text.split())):
        raise ValueError(f"Dòng #{ids[0] + 1}: lời đọc trống hoặc còn ký tự không đọc được.")
    if len(text) > 2000:
        raise ValueError(f"Dòng #{ids[0] + 1}: câu đọc quá dài. Hãy chia thành các câu ngắn hơn.")
    unit = {"cues": ids, "start": cues[ids[0]].start, "end": cues[ids[-1]].end,
            "speaker": cues[ids[0]].speaker, "text": text.strip()}
    if row.get("variant") is not None:
        if not isinstance(row["variant"], str) or not re.fullmatch("[0-9a-f]{32}", row["variant"]):
            raise ValueError(f"Dòng #{ids[0] + 1}: lượt đọc không hợp lệ. Hãy nghe lại.")
        unit["variant"] = row["variant"]
    return unit


def approved(cues, review, project, source, target, shorten):
    if not isinstance(review, dict) or not isinstance(review.get("units"), list):
        raise ValueError("Hãy xem và duyệt kịch bản sau dịch trước khi lồng tiếng.")
    issues = _issues(cues, _translated(cues, source, target))
    if issues:
        first = issues[0]
        raise ValueError(f"Dòng #{first['cue'] + 1}: {first['reason']}. Sửa rồi duyệt lại kịch bản.")
    if not 0 < len(review["units"]) <= len(cues):
        raise ValueError("Kịch bản không đủ câu đọc. Hãy dựng và duyệt lại.")
    units = [reading_unit(cues, row) for row in review["units"]]
    groups = [u["cues"] for u in units]
    if ([i for group in groups for i in group] != list(range(len(cues))) or
            review.get("revision") != _revision(cues, groups, project, source, target, shorten)):
        raise ValueError("Kịch bản thiếu dòng hoặc đã thay đổi. Hãy dựng và duyệt lại trước khi lồng tiếng.")
    return units
