"""/api/projects — mở lại, phát video, tải file và xoá dự án đã làm."""

from __future__ import annotations

import mimetypes
import sqlite3
import wave
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from ..core import dub_review, dubbing, media, voiceprint
from ..core.subtitles import Cue, shift_cues
from ..db import JobScope, get_db
from ..store import characters, projects
from . import access, auth
from .covers import cover_choice, uploaded_cover
from .deps import edited_cues, ranged_file, safe_id

router = APIRouter(prefix="/api/projects", tags=["projects"])


@router.get("")
def projects_list(user=Depends(auth.member)) -> dict:
    with get_db() as db:
        _, ids = access.library_ids(db, user)
    items = projects.list_all(only_ids=ids)
    return {"projects": items, "total_size": sum(it["size"] for it in items)}


@router.get("/{job_id}")
def project_get(job_id: str, user=Depends(auth.member)) -> dict:
    item = projects.full(Path(job_id).name)
    if not item:
        raise HTTPException(404, "Không tìm thấy dự án này (có thể đã bị xoá).")
    with get_db() as db:
        item["role"] = access.require(access.job_rights(db, user, job_id)[0], "viewer")
    return item


@router.get("/{job_id}/video")
def project_video(job_id: str, request: Request):
    path = projects.video_path(Path(job_id).name)
    if not path:
        raise HTTPException(
            404,
            "Video gốc của dự án không còn trên máy. Phụ đề vẫn xem và xuất được, "
            "nhưng không xem trước trên video và không nung được.",
        )
    mime = mimetypes.guess_type(path.name)[0] or "video/mp4"
    return ranged_file(path, request, mime)


@router.get("/{job_id}/thumbnail", response_class=Response, responses={200: {"content": {"image/jpeg": {}}}})
def project_thumbnail(job_id: str) -> Response:
    if job_id and safe_id(job_id) == job_id:
        try:
            for source in projects.thumbnail_sources(job_id):
                jpeg = media.thumbnail(source)
                if jpeg:
                    return Response(jpeg, media_type="image/jpeg")
        except OSError:
            pass  # The library can change between listing and opening a picture.
    raise HTTPException(404, "Không có khung hình cho dự án này.")


@router.post("/{job_id}/dub-review")
def approve_dub_review(job_id: str, payload: dict):
    if not safe_id(job_id) or job_id != safe_id(job_id):
        raise HTTPException(404, "Không tìm thấy dự án.")
    rows = edited_cues(payload.get("cues"))
    cues = [Cue.from_dict(c) for c in rows]
    review = payload.get("review")
    shorten = payload.get("shorten") is True
    try:
        units = dub_review.approved(cues, review, job_id, payload.get("source_lang"), payload.get("target_lang"), shorten)
        mix = None
        if payload.get("playback") is not None:
            mix = dub_review.playback(payload["playback"], cues)
            source = projects.audition_source(job_id)
            if source:
                takes = projects.audition_takes(job_id, source[0], cues)
                takes.bind(units, mix["voices"], mix["voice"], mix["style"])
                takes.check_timing(cues, units, mix, source[1])
        elif any(u.get("variant") for u in units):
            raise ValueError("Hãy chọn giọng trước khi duyệt lượt đọc mới.")
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    saved = {"revision": review["revision"], "shorten": shorten,
             "units": [{k: u[k] for k in ("cues", "text", "variant", "take") if k in u} for u in units]}
    if mix is not None:
        saved["playback"] = mix
    saved["token"] = projects.script_revision(saved)
    if not projects.save_cues(job_id, rows, str(payload.get("target_lang") or "")[:16], payload.get("revision"),
                              review=saved, previous_review=payload.get("previous")):
        raise HTTPException(404, "Không tìm thấy dự án để duyệt kịch bản.")
    return {"token": saved["token"], "revision": projects.script_revision(rows), "playback": mix}


class Audition(BaseModel):
    cues: list[dict] = Field(max_length=20000)
    unit: dict
    voice: str = Field(default="", max_length=128)
    style: str = Field(default="tu_nhien", max_length=32)
    max_speed: float = Field(default=1.5, ge=1, le=2)
    offset: float = Field(default=0, allow_inf_nan=False)
    duration: float = Field(default=0, ge=0, allow_inf_nan=False)
    another: bool = False


@router.post("/{job_id}/dub-preview", response_class=Response)
def project_dub_preview(job_id: str, payload: Audition):
    """Synthesize only the draft utterance. No render job, script save or video encode."""
    source = projects.audition_source(job_id) if job_id == safe_id(job_id) else None
    if source is None:
        raise HTTPException(404, "Không tìm thấy dự án để xem thử.")
    video, duration = source
    originals = [Cue.from_dict(c) for c in edited_cues(payload.cues, allow_blank=True)]
    cues = shift_cues([replace(c) for c in originals], payload.offset) if payload.offset else originals
    try:
        unit = dub_review.reading_unit(cues, payload.unit)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    if payload.another:
        unit["variant"] = uuid4().hex
    try:
        takes = projects.audition_takes(job_id, video, originals)
        with TemporaryDirectory() as tmp:
            folder = Path(tmp)

            def prepare_reference():
                clone = payload.voice == dubbing.CLONE_VOICE
                ok, why = dubbing.clone_available() if clone else dubbing.available()
                if not ok:
                    raise dubbing.DubError(why)
                if not clone:
                    if payload.voice and payload.voice not in {v["id"] for v in dubbing.list_voices()}:
                        raise dubbing.DubError("Giọng đã chọn không còn trong danh sách.")
                    return None
                dirs = projects.audio_dirs(job_id)
                src = next((d / n for n in ("vocals.wav", "audio.wav") for d in dirs if (d / n).is_file()), None)
                src = src or video
                if not src:
                    raise dubbing.DubError("Không còn tiếng gốc để lấy mẫu. Hãy chọn một giọng có sẵn.")
                ref = folder / "reference.wav"
                sid = unit["speaker"]
                if not sid or not dubbing.compose_reference(src, originals, ref, sid):
                    dubbing.extract_reference(src, originals, ref, speaker=sid)
                return ref

            path, start, over = dubbing.audition_unit(
                cues, unit, payload.voice, payload.style, payload.max_speed, folder,
                duration or payload.duration, takes, prepare_reference, new_variant=payload.another)
            return Response(path.read_bytes(), media_type="audio/wav", headers={
                "X-Preview-Start": str(start), "X-Preview-Overrun": str(over),
                "X-Preview-Variant": unit.get("variant", ""),
                "Access-Control-Expose-Headers": "X-Preview-Start, X-Preview-Overrun, X-Preview-Variant"})
    except (RuntimeError, OSError, ValueError, sqlite3.Error) as exc:
        raise HTTPException(422, f"Không nghe thử được: {exc}") from exc


@router.get("/{job_id}/cover", response_class=Response)
def project_cover(job_id: str):
    with get_db() as db:
        scope = db.get(JobScope, job_id) if projects.exists(job_id) else None
        return uploaded_cover(scope.cover_jpeg if scope else None)


@router.post("/{job_id}/cover")
def set_project_cover(job_id: str, jpeg=Depends(cover_choice)):
    if not projects.exists(job_id):
        raise HTTPException(404, "Không tìm thấy video trong thư viện.")
    with get_db() as db:
        scope = db.get(JobScope, job_id)
        if scope:
            scope.cover_jpeg = jpeg
        elif jpeg is not None:
            # An admin may set a cover for an unassigned legacy project without claiming it.
            db.add(JobScope(id=job_id, cover_jpeg=jpeg))
    return {"has_cover": jpeg is not None}


@router.put("/{job_id}/cues")
def project_save_cues(job_id: str, payload: dict) -> dict:
    rows = edited_cues(payload.get("cues"))
    job_id = safe_id(job_id)
    if not job_id or not projects.save_cues(job_id, rows, str(payload.get("target_lang") or "")[:16], payload.get("revision")):
        raise HTTPException(404, "Không tìm thấy dự án để lưu kịch bản.")
    return {"cue_count": len(rows), "revision": projects.script_revision(rows)}


@router.post("/{job_id}/speakers")
def project_identify_speakers(job_id: str, payload: dict) -> dict:
    job_id = safe_id(job_id)
    item = projects.full(job_id) if job_id else None
    if item is None:
        raise HTTPException(404, "Không tìm thấy dự án để phân giọng.")
    rows = edited_cues(payload.get("cues"))
    expected = projects.speaker_timing(rows)
    if not rows:
        raise HTTPException(400, "Chưa có câu thoại để phân giọng.")
    if expected != projects.speaker_timing(item["cues"]):
        raise HTTPException(409, "Mốc giờ hoặc vai chưa khớp kịch bản đã lưu. Lưu kịch bản rồi phân giọng lại.")

    folders = projects.audio_dirs(job_id)
    # A previous export can contain the clean stem even if analysis only saved the mix.
    wav = next((d / name for name in ("vocals.wav", "audio.wav") for d in folders
                if (d / name).is_file()), None)
    cues = [Cue.from_dict(c) for c in item["cues"]]
    try:
        with TemporaryDirectory() as tmp:
            if wav is None:
                video = projects.video_path(job_id)
                if not video:
                    raise HTTPException(410, "Không còn rãnh tiếng hoặc video gốc để phân giọng.")
                wav = media.extract_audio(video, Path(tmp) / "audio.wav")
            speakers, method = voiceprint.identify(wav, cues, reserved_ids=[c["label"] for c in item["characters"]])
    except (OSError, EOFError, wave.Error, ValueError, media.MediaError) as exc:
        raise HTTPException(422, f"Không đọc được tiếng gốc để phân giọng: {exc}") from exc
    if not speakers:
        raise HTTPException(422, "Không nghe đủ tiếng nói ở các mốc phụ đề. Các vai cũ vẫn được giữ.")
    labels = [c.speaker for c in cues]
    revision = projects.save_speakers(job_id, expected, labels, speakers, payload.get("revision"))
    if not revision:
        raise HTTPException(409, "Kịch bản đã đổi trong lúc phân giọng; không ghi đè kết quả.")
    try:
        characters.sync(job_id, speakers, keep_cast=True)
    except Exception:
        pass  # The script and its cast are already saved; custom voices remain untouched.
    return {"labels": labels, "speakers": speakers, "method": method, "revision": revision}


@router.post("/{job_id}/hardsub")
def project_hardsub(job_id: str) -> dict:
    """Dò lại dải phụ đề nung sẵn trong video của dự án (nút "Dò lại" ở bước 4)."""
    from ..core import hardsub
    from ..core.subtitles import Cue

    job_id = Path(job_id).name
    item = projects.full(job_id)
    if not item:
        raise HTTPException(404, "Không tìm thấy dự án này.")
    video = projects.video_path(job_id)
    if not video:
        raise HTTPException(404, "Video gốc của dự án không còn trên máy nên không dò được.")
    cues = [Cue.from_dict(c) for c in item.get("cues") or []]
    try:
        result = hardsub.detect(video, cues)
    except Exception as exc:
        raise HTTPException(500, f"Không dò được: {exc}") from exc
    projects.save_hardsub(job_id, result)
    return result


# Các rãnh sóng âm của dòng thời gian: (id, nhãn, tên file trong thư mục job)
_WAVE_TRACKS = (
    ("vocals", "Giọng gốc", "vocals.wav"),
    ("music", "Nhạc nền", "no_vocals.wav"),
    ("audio", "Tiếng gốc", "audio.wav"),
)


@router.get("/{job_id}/waveform")
def project_waveform(job_id: str, points: int = 2000) -> dict:
    """Đỉnh sóng âm để vẽ dòng thời gian ở bước 4.

    Đã tách giọng (lúc phân tích hoặc ở một lần xuất trước) thì trả hai rãnh giọng gốc /
    nhạc nền; chưa tách thì trả một rãnh tiếng gốc. Không có file âm thanh nào thì
    `tracks` rỗng — giao diện chỉ việc không vẽ sóng.
    """
    from ..core import waveform

    job_id = Path(job_id).name
    if not projects.full(job_id):
        raise HTTPException(404, "Không tìm thấy dự án này.")
    found: dict[str, Path] = {}
    for folder in projects.audio_dirs(job_id):
        for tid, _label, name in _WAVE_TRACKS:
            if tid not in found and (folder / name).is_file():
                found[tid] = folder / name
    wanted = ["vocals", "music"] if "vocals" in found and "music" in found else ["audio"]
    tracks, duration = [], 0.0
    for tid, label, _name in _WAVE_TRACKS:
        if tid not in wanted or tid not in found:
            continue
        try:
            data, seconds = waveform.cached_peaks(found[tid], points)
        except Exception:
            continue  # file hỏng / không phải PCM 16 bit: bỏ rãnh đó
        tracks.append({"id": tid, "label": label, "peaks": data})
        duration = max(duration, seconds)
    return {"duration": round(duration, 3), "tracks": tracks}


@router.get("/{job_id}/files/{name}")
def project_file(job_id: str, name: str, download: int = 1):
    path = projects.output_file(Path(job_id).name, name)
    if not path:
        raise HTTPException(404, "File không tồn tại.")
    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    inline = not download and mime.startswith(("video/", "audio/"))
    return FileResponse(path, media_type=mime, filename=path.name,
                        content_disposition_type="inline" if inline else "attachment")


@router.get("/{job_id}/characters")
def project_characters(job_id: str) -> dict:
    """Bảng nhân vật → giọng của dự án (HP-2), đọc từ DB."""
    job_id = Path(job_id).name
    if not projects.summary(job_id):
        raise HTTPException(404, "Không tìm thấy dự án này.")
    return {"characters": characters.list_for(job_id)}


@router.patch("/{job_id}/characters/{label}")
def project_character_update(job_id: str, label: str, payload: dict) -> dict:
    """Đổi tên vai / chọn giọng cho một nhân vật; lưu để mở lại dự án vẫn còn."""
    job_id = Path(job_id).name
    if not projects.summary(job_id):
        raise HTTPException(404, "Không tìm thấy dự án này.")
    data = payload or {}
    try:
        item = characters.update(
            job_id, label,
            name=data.get("name"), voice=data.get("voice"), style=data.get("style"),
            gender=data.get("gender"), age=data.get("age"),
        )
    except characters.CharacterError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"ok": True, "character": item}


@router.delete("/{job_id}")
def project_delete(job_id: str, with_source: int = 0, user=Depends(auth.member)) -> dict:
    result = projects.delete(job_id, with_source=bool(with_source), source_owner_id=None if user["role"] == "admin" else user["id"])
    if not result["ok"]:
        raise HTTPException(404, "Không tìm thấy dự án này.")
    return result
