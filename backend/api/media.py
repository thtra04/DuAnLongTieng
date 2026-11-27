"""/api/link, /api/upload, /api/media — đưa video vào và phát lại."""

from __future__ import annotations

import mimetypes
import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile

from ..config import JOB_DIR, MAX_UPLOAD_BYTES, UPLOAD_DIR
from ..core import media, pipeline
from ..db import UploadOwner, get_db
from . import access, auth
from .deps import VIDEO_EXT, ranged_file, remote_source

router = APIRouter(prefix="/api", tags=["media"])


@router.post("/link/inspect")
def link_inspect(payload: dict) -> dict:
    """Xem link có nhiều phần không, để hỏi người dùng chọn phần nào.

    Bilibili (và playlist YouTube) hay gộp nhiều tập trong một link — mỗi tập
    có thể dài mấy tiếng, nên phải hỏi trước khi tải.
    """
    url = ((payload or {}).get("url") or "").strip()
    if not url:
        raise HTTPException(400, "Thiếu link video.")
    url = remote_source(url)
    try:
        return media.list_parts(url)
    except media.MediaError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(400, f"Không đọc được link: {exc}") from exc


@router.post("/upload")
async def upload(file: UploadFile = File(...), user=Depends(auth.member)) -> dict:
    ext = Path(file.filename or "video.mp4").suffix.lower() or ".mp4"
    if ext not in VIDEO_EXT:
        raise HTTPException(400, f"Định dạng không hỗ trợ: {ext}")

    media_id = uuid.uuid4().hex[:12]
    target_dir = UPLOAD_DIR / media_id
    target_dir.mkdir(parents=True, exist_ok=True)
    dest = target_dir / (pipeline.safe_stem(file.filename or "video") + ext)

    size = 0
    with dest.open("wb") as fh:
        while chunk := await file.read(1024 * 1024):
            size += len(chunk)
            if size > MAX_UPLOAD_BYTES:
                fh.close()
                shutil.rmtree(target_dir, ignore_errors=True)
                raise HTTPException(413, "File quá lớn.")
            fh.write(chunk)

    try:
        info = media.probe(dest)
    except Exception as exc:
        shutil.rmtree(target_dir, ignore_errors=True)
        raise HTTPException(400, f"Không đọc được video: {exc}") from exc

    # `probe` trả về số 0 chứ không ném lỗi khi file không phải media, nên một
    # file rác vẫn qua được tới tận bước nghe rồi mới hỏng. Chặn ngay ở đây.
    if not info.get("duration") and not info.get("width") and not info.get("has_audio"):
        shutil.rmtree(target_dir, ignore_errors=True)
        raise HTTPException(
            400,
            "File này không phải video hay âm thanh đọc được. "
            "Kiểm tra lại file, hoặc thử đổi sang .mp4 rồi tải lên lại.",
        )

    with get_db() as db:
        db.add(UploadOwner(id=media_id, member_id=user["id"]))
    return {
        "media_id": media_id,
        "name": dest.name,
        "size": size,
        "path": str(dest),
        "info": info,
    }


@router.get("/media/{media_id}/stream")
def stream_media(media_id: str, request: Request, user=Depends(auth.member)):
    media_id = access.key(media_id)
    if not media_id:
        raise HTTPException(404, "Không tìm thấy media.")
    folder = UPLOAD_DIR / media_id
    with get_db() as db:
        if folder.is_dir():
            access.upload_right(db, user, media_id)
        else:
            access.require(access.job_rights(db, user, media_id)[0], "viewer")
            folder = JOB_DIR / media_id / "source"
    files = [p for p in folder.glob("*") if p.is_file()] if folder.is_dir() else []
    if not files:
        raise HTTPException(404, "Không tìm thấy media.")
    path = files[0]
    mime = mimetypes.guess_type(path.name)[0] or "video/mp4"
    return ranged_file(path, request, mime)
