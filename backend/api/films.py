"""/api/films — bộ phim và tập: tạo bộ → tạo tập → gắn video/job vào tập."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException

from ..core import media
from ..store import films, projects, series

router = APIRouter(prefix="/api/films", tags=["films"])


@router.get("")
def films_list() -> dict:
    """Nội dung dashboard: các bộ phim kèm tập, và job chưa thuộc bộ nào."""
    return projects.dashboard()


@router.post("")
def film_create(payload: dict) -> dict:
    """Tạo bộ phim.

    Có `url` thì đọc luôn link để tạo sẵn từng tập, và tự gắn những tập đã làm
    trước đó (job cũ cùng link, cùng số phần) vào đúng chỗ.
    """
    data = payload or {}
    parts: list[dict] = []
    url = (data.get("url") or "").strip()

    if url:
        try:
            info = media.list_parts(url)
        except media.MediaError as exc:
            raise HTTPException(400, str(exc)) from exc
        parts = info.get("parts") or []
        if not parts:  # link một video -> bộ một tập
            parts = [{"index": 1, "title": info.get("title") or "", "duration": info.get("duration") or 0}]
        if not (data.get("name") or "").strip():
            data["name"] = info.get("title") or url

    try:
        film = films.create(data.get("name") or "", url=url, parts=parts)
    except films.FilmError as exc:
        raise HTTPException(400, str(exc)) from exc

    adopted = _adopt_existing(film) if url else 0
    return {"film": film, "adopted": adopted}


def _adopt_existing(film: dict) -> int:
    """Gắn các job cũ cùng link vào tập tương ứng của bộ mới tạo.

    Chỉ chạy đúng một lần lúc tạo bộ, và chỉ nhận job chưa thuộc bộ nào — cố ý
    không đoán ngầm về sau, để dashboard chỉ có một quy tắc: bộ do bạn tạo.
    """
    key = series.key_for(film.get("url") or "")
    if not key:
        return 0
    bound = films.bound_jobs()
    numbers = {int(e.get("no") or 0) for e in film.get("episodes") or []}

    count = 0
    for item in projects.list_all(limit=10_000):
        if item["id"] in bound or item["series_key"] != key:
            continue
        part = item["part"] or 1
        if part not in numbers:
            continue
        try:
            films.bind(film["id"], part, item["id"])
            count += 1
        except films.FilmError:
            continue
    return count


@router.patch("/{film_id}")
def film_rename(film_id: str, payload: dict) -> dict:
    try:
        film = films.rename(film_id, (payload or {}).get("name") or "")
    except films.FilmError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"ok": True, "film": film}


@router.delete("/{film_id}")
def film_delete(film_id: str, with_jobs: int = 1, with_source: int = 1) -> dict:
    """Xoá bộ. `with_jobs=1` (mặc định) xoá luôn phụ đề & file của mọi tập."""
    try:
        film = films.remove(film_id)
    except films.FilmError as exc:
        raise HTTPException(404, str(exc)) from exc

    freed, removed = 0, 0
    if with_jobs:
        for episode in film.get("episodes") or []:
            job_id = episode.get("job")
            if not job_id:
                continue
            result = projects.delete(job_id, with_source=bool(with_source))
            if result["ok"]:
                removed += 1
                freed += result["freed"]
    return {"ok": True, "removed": removed, "freed": freed}


@router.post("/{film_id}/episodes")
def episode_add(film_id: str, payload: dict) -> dict:
    data = payload or {}
    raw_no = data.get("no")
    try:
        no = int(raw_no) if raw_no not in (None, "") else None
    except (TypeError, ValueError):
        raise HTTPException(400, "Số tập không hợp lệ.") from None
    try:
        episode = films.add_episode(film_id, no=no, title=data.get("title") or "")
    except films.FilmError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"ok": True, "episode": episode}


@router.delete("/{film_id}/episodes/{no}")
def episode_remove(film_id: str, no: int, with_job: int = 1, with_source: int = 1) -> dict:
    try:
        episode = films.remove_episode(film_id, no)
    except films.FilmError as exc:
        raise HTTPException(404, str(exc)) from exc
    if not episode:
        raise HTTPException(404, f"Bộ này không có tập {no}.")

    freed = 0
    job_id = episode.get("job")
    if with_job and job_id:
        result = projects.delete(job_id, with_source=bool(with_source))
        freed = result["freed"]
    return {"ok": True, "freed": freed}


@router.post("/{film_id}/episodes/{no}/bind")
def episode_bind(film_id: str, no: int, payload: dict) -> dict:
    """Gắn một job đã làm sẵn vào tập — dùng cho mục 'chưa thuộc bộ nào'."""
    job_id = ((payload or {}).get("job") or "").strip()
    if not job_id:
        raise HTTPException(400, "Thiếu id dự án cần gắn.")
    if not projects.summary(Path(job_id).name):
        raise HTTPException(404, "Không tìm thấy dự án cần gắn.")
    try:
        episode = films.bind(film_id, no, Path(job_id).name)
    except films.FilmError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"ok": True, "episode": episode}
