"""Quản lý dự án video — đọc lại việc đã làm từ đĩa.

Mỗi lần phân tích xong, pipeline ghi `data/jobs/<id>/state.json` gồm đường dẫn
video, ngôn ngữ và toàn bộ dòng phụ đề. Danh sách job trong RAM mất khi khởi
động lại tool, nhưng `state.json` vẫn nằm đó — module này đọc lại chỗ đó để
người dùng mở lại việc cũ mà không phải nghe & dịch lại từ đầu.

Chỗ này chỉ đọc và xoá thư mục job. Video gốc do người dùng tự upload nằm ở
`data/uploads/<media_id>/` và có thể được nhiều dự án dùng chung, nên không bị
xoá kèm — trừ khi gọi `delete()` với `with_source=True`, lúc đó mới kiểm tra
xem còn dự án nào trỏ tới nó không.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from . import series
from .config import JOB_DIR, UPLOAD_DIR

# Đuôi file được coi là kết quả xuất ra, đáng cho người dùng tải lại
_OUTPUT_EXT = {".srt", ".vtt", ".txt", ".ass", ".mp4", ".mkv", ".webm", ".wav"}
# File làm việc nội bộ của pipeline — không phải kết quả
_INTERNAL = {
    "state.json", "render.json", "burn.ass", "audio.wav", "dub.wav",
    "voice_ref.wav", "_soft.srt",
}


def _render_dirs(job_id: str) -> list[Path]:
    """Các thư mục job render đã xuất file cho dự án này.

    `run_render` ghi kết quả vào thư mục của chính job render, nên file xuất ra
    không nằm cùng chỗ với `state.json`. Mỗi job render để lại `render.json`
    trỏ về dự án gốc — đọc chỗ đó để gom lại.
    """
    found: list[Path] = []
    if not JOB_DIR.is_dir():
        return found
    for folder in JOB_DIR.iterdir():
        marker = folder / "render.json"
        if not marker.is_file():
            continue
        try:
            data = json.loads(marker.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict) and data.get("source_job") == job_id:
            found.append(folder)
    found.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return found


def _dir_size(folder: Path) -> int:
    total = 0
    for path in folder.rglob("*"):
        try:
            if path.is_file():
                total += path.stat().st_size
        except OSError:
            pass
    return total


def _output_paths(job_id: str) -> list[Path]:
    """File kết quả của dự án: trong thư mục job, và trong các job render của nó.

    Trùng tên (xuất lại nhiều lần) thì giữ bản mới nhất.
    """
    by_name: dict[str, Path] = {}
    for folder in [JOB_DIR / job_id, *_render_dirs(job_id)]:
        if not folder.is_dir():
            continue
        for path in sorted(folder.glob("*")):
            if not path.is_file() or path.name in _INTERNAL:
                continue
            if path.suffix.lower() not in _OUTPUT_EXT:
                continue
            old = by_name.get(path.name)
            if old is None or path.stat().st_mtime > old.stat().st_mtime:
                by_name[path.name] = path
    return [by_name[name] for name in sorted(by_name)]


def _outputs(job_id: str) -> list[dict]:
    return [
        {
            "name": path.name,
            "size": path.stat().st_size,
            "kind": path.suffix.lstrip(".").lower(),
        }
        for path in _output_paths(job_id)
    ]


def _read_state(job_id: str) -> tuple[Path, dict] | None:
    folder = JOB_DIR / job_id
    state_path = folder / "state.json"
    if not state_path.is_file():
        return None
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(state, dict):
        return None
    return folder, state


def summary(job_id: str) -> dict | None:
    """Thông tin gọn của một dự án (không kèm phụ đề). None nếu không đọc được."""
    found = _read_state(job_id)
    if not found:
        return None
    folder, state = found

    info = state.get("info") or {}
    cfg = state.get("cfg") or {}
    video = Path(state.get("video_path") or "")
    return {
        "id": job_id,
        "video_name": state.get("video_name") or video.name or "(không rõ tên)",
        "duration": float(info.get("duration") or 0.0),
        "width": int(info.get("width") or 0),
        "height": int(info.get("height") or 0),
        "source_lang": state.get("source_lang") or "",
        "target_lang": state.get("target_lang") or "",
        "cue_count": len(state.get("cues") or []),
        "updated": (folder / "state.json").stat().st_mtime,
        "size": _dir_size(folder) + sum(_dir_size(d) for d in _render_dirs(job_id)),
        # Video gốc còn trên máy không — không còn thì chỉ xem/sửa được phụ đề
        "video_ok": video.is_file(),
        "source_url": cfg.get("url") or "",
        "part": cfg.get("part") or None,
        # Tên bộ & tổng số tập do trình duyệt gửi kèm lúc chọn phần (xem
        # /api/link/inspect). Dự án cũ làm trước khi có tính năng này thì trống.
        "series_name": (cfg.get("series_name") or "").strip(),
        "series_total": int(cfg.get("series_total") or 0),
        "series_key": series.key_for(cfg.get("url") or ""),
        "files": _outputs(job_id),
    }


def list_all(limit: int = 80) -> list[dict]:
    """Các dự án đọc được, mới nhất trước."""
    if not JOB_DIR.is_dir():
        return []
    items: list[dict] = []
    for folder in JOB_DIR.iterdir():
        if not folder.is_dir():
            continue
        item = summary(folder.name)
        if item:
            items.append(item)
    items.sort(key=lambda it: it["updated"], reverse=True)
    return items[:limit]


def dashboard() -> dict:
    """Toàn bộ nội dung dashboard: các bộ phim (kèm tập) + job chưa thuộc bộ nào.

    Bộ phim và tập lấy từ `films.json` — do người dùng tạo. Mỗi tập có `job`
    hoặc không: có thì gắn kèm thông tin phụ đề, không thì trạng thái là
    "chưa có video". Job nào không tập nào trỏ tới thì xếp vào `loose`.
    """
    from . import films  # nạp muộn: films chỉ là kho, không phụ thuộc chiều ngược

    by_id = {item["id"]: item for item in list_all(limit=10_000)}
    bound = films.bound_jobs()

    result: list[dict] = []
    for film in films.all_films():
        episodes: list[dict] = []
        for episode in sorted(film.get("episodes") or [], key=lambda e: int(e.get("no") or 0)):
            job_id = episode.get("job")
            project = by_id.get(job_id) if job_id else None
            episodes.append(
                {
                    "no": int(episode.get("no") or 0),
                    "title": episode.get("title") or "",
                    # tập chưa làm vẫn biết dài bao lâu nếu lấy được từ link
                    "duration": float(project["duration"] if project else (episode.get("duration") or 0.0)),
                    "job": job_id if project else None,
                    "project": project,
                    # job từng gắn nhưng thư mục đã bị xoá -> coi như chưa làm
                    "stale": bool(job_id and not project),
                }
            )

        done = [e for e in episodes if e["project"]]
        result.append(
            {
                "id": film.get("id") or "",
                "name": film.get("name") or "(chưa đặt tên)",
                "url": film.get("url") or "",
                "created": float(film.get("created") or 0.0),
                "episodes": episodes,
                "total": len(episodes),
                "done": len(done),
                "duration": sum(e["duration"] for e in episodes),
                "size": sum(e["project"]["size"] for e in done),
                "updated": max((e["project"]["updated"] for e in done), default=float(film.get("created") or 0.0)),
            }
        )

    loose = [item for job_id, item in by_id.items() if job_id not in bound]
    loose.sort(key=lambda it: it["updated"], reverse=True)

    return {
        "films": result,
        "loose": loose,
        "total_films": len(result),
        "total_episodes": sum(f["done"] for f in result),
        "total_size": sum(f["size"] for f in result) + sum(it["size"] for it in loose),
    }


def full(job_id: str) -> dict | None:
    """Như `summary` nhưng kèm toàn bộ dòng phụ đề, để mở lại trong trình biên tập."""
    found = _read_state(job_id)
    if not found:
        return None
    item = summary(job_id)
    if item is None:
        return None
    item["cues"] = found[1].get("cues") or []
    return item


def video_path(job_id: str) -> Path | None:
    """File video gốc của dự án, nếu còn trên máy."""
    found = _read_state(job_id)
    if not found:
        return None
    folder, state = found

    candidate = Path(state.get("video_path") or "")
    if candidate.is_file():
        return candidate

    # state.json còn nhưng video đã bị dọn/di chuyển: thử lại trong thư mục job
    source = folder / "source"
    if source.is_dir():
        for path in sorted(source.glob("*")):
            if path.is_file():
                return path
    return None


def output_file(job_id: str, name: str) -> Path | None:
    """File kết quả để tải về. Chỉ nhận tên file trần, không nhận `../`."""
    wanted = Path(name).name
    for path in _output_paths(job_id):
        if path.name == wanted:
            return path
    return None


def delete(job_id: str, with_source: bool = False) -> dict:
    """Xoá dự án: thư mục job + các thư mục render của nó.

    Trả về {ok, freed, source_deleted}.
    """
    folder = JOB_DIR / job_id
    if not folder.is_dir():
        return {"ok": False, "freed": 0, "source_deleted": False}

    upload_dir = None
    if with_source:
        video = video_path(job_id)
        if video:
            upload_dir = _upload_folder_of(video)

    renders = _render_dirs(job_id)
    freed = _dir_size(folder) + sum(_dir_size(d) for d in renders)
    shutil.rmtree(folder, ignore_errors=True)
    for rendered in renders:
        shutil.rmtree(rendered, ignore_errors=True)

    # Tập đang trỏ tới job này phải quay về trạng thái "chưa có video"
    from . import films

    films.unbind_job(job_id)

    source_deleted = False
    # Chỉ xoá video upload khi không còn dự án nào khác dùng nó
    if upload_dir and upload_dir.is_dir() and not _upload_in_use(upload_dir):
        freed += _dir_size(upload_dir)
        shutil.rmtree(upload_dir, ignore_errors=True)
        source_deleted = not upload_dir.exists()

    return {"ok": not folder.exists(), "freed": freed, "source_deleted": source_deleted}


def _upload_folder_of(video: Path) -> Path | None:
    """Thư mục `uploads/<media_id>` chứa video này, nếu nó nằm trong uploads."""
    try:
        rel = video.resolve().relative_to(UPLOAD_DIR.resolve())
    except (ValueError, OSError):
        return None
    return UPLOAD_DIR / rel.parts[0] if rel.parts else None


def _upload_in_use(upload_dir: Path) -> bool:
    """Còn dự án nào trỏ video vào thư mục upload này không."""
    target = upload_dir.resolve()
    for item in list_all(limit=10_000):
        found = _read_state(item["id"])
        if not found:
            continue
        candidate = Path(found[1].get("video_path") or "")
        try:
            if candidate.resolve().is_relative_to(target):
                return True
        except (OSError, ValueError):
            continue
    return False
