"""/api/projects — mở lại, phát video, tải file và xoá dự án đã làm."""

from __future__ import annotations

import mimetypes
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

from ..store import characters, projects
from .deps import ranged_file

router = APIRouter(prefix="/api/projects", tags=["projects"])


@router.get("")
def projects_list() -> dict:
    items = projects.list_all()
    return {"projects": items, "total_size": sum(it["size"] for it in items)}


@router.get("/{job_id}")
def project_get(job_id: str) -> dict:
    item = projects.full(Path(job_id).name)
    if not item:
        raise HTTPException(404, "Không tìm thấy dự án này (có thể đã bị xoá).")
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


@router.get("/{job_id}/files/{name}")
def project_file(job_id: str, name: str):
    path = projects.output_file(Path(job_id).name, name)
    if not path:
        raise HTTPException(404, "File không tồn tại.")
    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return FileResponse(path, media_type=mime, filename=path.name)


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
        )
    except characters.CharacterError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"ok": True, "character": item}


@router.delete("/{job_id}")
def project_delete(job_id: str, with_source: int = 0) -> dict:
    result = projects.delete(Path(job_id).name, with_source=bool(with_source))
    if not result["ok"]:
        raise HTTPException(404, "Không tìm thấy dự án này.")
    return result
