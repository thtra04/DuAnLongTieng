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

import hashlib
import json
import shutil
import threading
from collections.abc import Iterator
from tempfile import NamedTemporaryFile
from pathlib import Path

from . import characters, films, series
from ..config import JOB_DIR, UPLOAD_DIR
from ..core.dub_takes import AuditionTakes
from ..db import JobScope, UploadOwner, get_db

# Đuôi file được coi là kết quả xuất ra, đáng cho người dùng tải lại
_OUTPUT_EXT = {".srt", ".vtt", ".txt", ".ass", ".mp4", ".mkv", ".webm", ".wav"}
_PICTURE_VIDEO_EXT = {".mp4", ".m4v", ".mov", ".mkv", ".webm", ".avi", ".flv", ".ts", ".wmv"}
# File làm việc nội bộ của pipeline — không phải kết quả
_INTERNAL = {
    "state.json", "render.json", "burn.ass", "audio.wav", "dub.wav",
    "voice_ref.wav", "_soft.srt",
}
_script_lock = threading.Lock()


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


def audio_dirs(job_id: str) -> list[Path]:
    """Thư mục có thể chứa file âm thanh của dự án: job phân tích trước, rồi các lần xuất (mới nhất trước)."""
    renders = sorted(_render_dirs(job_id), key=lambda p: p.stat().st_mtime, reverse=True)
    return [JOB_DIR / job_id, *renders]


def audition_takes(job_id, video, cues):
    return AuditionTakes(JOB_DIR / job_id, video, cues)


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
    source = _source_file(folder, state)
    files = _outputs(job_id)
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
        "video_ok": source is not None,
        "has_thumbnail": bool(source and source.suffix.lower() in _PICTURE_VIDEO_EXT)
                         or any(Path(f["name"]).suffix.lower() in _PICTURE_VIDEO_EXT for f in files),
        "source_url": cfg.get("url") or "",
        "part": cfg.get("part") or None,
        # Tên bộ & tổng số tập do trình duyệt gửi kèm lúc chọn phần (xem
        # /api/link/inspect). Dự án cũ làm trước khi có tính năng này thì trống.
        "series_name": (cfg.get("series_name") or "").strip(),
        "series_total": int(cfg.get("series_total") or 0),
        "series_key": series.key_for(cfg.get("url") or ""),
        "files": files,
    }


def list_all(limit: int = 80, only_ids=None) -> list[dict]:
    """Các dự án đọc được, mới nhất trước."""
    if not JOB_DIR.is_dir():
        return []
    items: list[dict] = []
    for folder in JOB_DIR.iterdir():
        if (only_ids is not None and folder.name not in only_ids) or not folder.is_dir():
            continue
        item = summary(folder.name)
        if item:
            items.append(item)
    items.sort(key=lambda it: it["updated"], reverse=True)
    return items[:limit]


def dashboard(film_roles=None, job_ids=None) -> dict:
    """Toàn bộ nội dung dashboard: các bộ phim (kèm tập) + job chưa thuộc bộ nào.

    Bộ phim và tập lấy từ `films.json` — do người dùng tạo. Mỗi tập có `job`
    hoặc không: có thì gắn kèm thông tin phụ đề, không thì trạng thái là
    "chưa có video". Job nào không tập nào trỏ tới thì xếp vào `loose`.
    """
    by_id = {item["id"]: item for item in list_all(limit=10_000, only_ids=job_ids)}
    if by_id:
        with get_db() as db:
            for job_id, in db.query(JobScope.id).filter(JobScope.id.in_(by_id), JobScope.has_cover):
                by_id[job_id]["has_cover"] = True
    bound = films.bound_jobs()

    result: list[dict] = []
    for film in films.all_films(film_roles):
        episodes: list[dict] = []
        for episode in sorted(film.get("episodes") or [], key=lambda e: int(e.get("no") or 0)):
            job_id = episode.get("job")
            project = by_id.get(job_id) if job_id else None
            episodes.append(
                {
                    "no": int(episode.get("no") or 0),
                    "title": episode.get("title") or "",
                    "has_cover": bool(episode.get("has_cover")),
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
                "has_cover": bool(film.get("has_cover")),
                "team_id": film.get("team_id"),
                "legacy": film.get("legacy", False),
                "role": film_roles[film["id"]] if film_roles is not None else "owner",
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
    item["revision"] = script_revision(item["cues"])
    item["dub_review"] = found[1].get("dub_review")
    item["speakers"] = found[1].get("speakers") or []
    item["speech_gaps"] = found[1].get("speech_gaps") or []
    item["hardsub"] = found[1].get("hardsub") or None
    # Tên vai & giọng người dùng đã chọn — nằm trong DB, không nằm trong state.json.
    # DB hỏng thì vẫn mở được dự án, chỉ mất phần này.
    try:
        item["characters"] = characters.list_for(job_id)
    except Exception:
        item["characters"] = []
    return item


def save_hardsub(job_id: str, result: dict) -> None:
    """Ghi kết quả dò phụ đề nung sẵn vào state.json của dự án."""
    with _script_lock:
        found = _read_state(job_id)
        if found:
            folder, state = found
            state["hardsub"] = result
            _write_state(folder, state)


def _write_state(folder: Path, state: dict) -> None:
    pending = NamedTemporaryFile(mode="w", dir=folder, encoding="utf-8", delete=False)
    temp = Path(pending.name)
    try:
        with pending as f:
            json.dump(state, f, ensure_ascii=False, indent=1)
        temp.replace(folder / "state.json")
    finally:
        temp.unlink(missing_ok=True)


class ScriptChanged(RuntimeError):
    pass


def script_revision(cues):
    data = json.dumps(cues, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(data).hexdigest()


def check_revision(cues, expected):
    if expected is not None and script_revision(cues) != expected:
        raise ScriptChanged("Kịch bản đã được người khác sửa. Mở lại dự án để đối chiếu; chưa ghi đè.")


def commit_script(path, state, expected, expected_review=None):
    with _script_lock:
        if path.is_file():
            saved = json.loads(path.read_text(encoding="utf-8"))
            check_revision(saved.get("cues") or [], expected)
            if expected_review and (saved.get("dub_review") or {}).get("token") != expected_review:
                raise ScriptChanged("Bản duyệt đã đổi. Mở lại kịch bản trước khi lồng tiếng.")
            if "dub_review" in saved:
                state["dub_review"] = saved["dub_review"]
            if "hardsub" in saved:
                state["hardsub"] = saved["hardsub"]
        elif expected is not None:
            raise ScriptChanged("Dự án không còn tồn tại; chưa ghi kết quả.")
        _write_state(path.parent, state)


def save_cues(job_id: str, cues: list[dict], target_lang: str = "", expected=None, *,
              review=None, previous_review=None) -> bool:
    with _script_lock:
        found = _read_state(job_id)
        if not found:
            return False
        folder, state = found
        old = state.get("cues") or []
        if review is not None:
            if (state.get("dub_review") or {}).get("token") != previous_review:
                raise ScriptChanged("Bản duyệt đã đổi ở phiên khác. Mở lại để đối chiếu.")
            if expected is None and old != cues:
                raise ScriptChanged("Cần phiên bản phụ đề hiện tại để lưu bản duyệt. Hãy mở lại dự án.")
            state["dub_review"] = review
        check_revision(old, expected)
        state["cues"] = cues
        if not state.get("target_lang") and target_lang:
            state["target_lang"] = target_lang
        _write_state(folder, state)
    try:
        from . import memory

        if state.get("target_lang") and old != cues:
            memory.learn_from_edit(old, cues, state.get("source_lang") or "", state["target_lang"], job_id)
    except Exception:
        pass  # A memory failure must not turn a successful script save into an error.
    return True


def speaker_timing(rows: list[dict]) -> list[tuple]:
    return [(round(c["start"], 3), round(c["end"], 3), c.get("speaker") or "",
             c.get("speaker_fixed") is True) for c in rows]


def save_speakers(job_id: str, expected: list[tuple], labels: list[str], speakers: list[dict], revision=None):
    """Commit only speaker assignments; never overwrite a newer edit with the analysis snapshot."""
    with _script_lock:
        found = _read_state(job_id)
        if not found:
            return False
        folder, state = found
        rows = state.get("cues") or []
        check_revision(rows, revision)
        if len(labels) != len(rows) or speaker_timing(rows) != expected:
            return False
        for row, label in zip(rows, labels):
            row["speaker"] = label
        state["speakers"] = speakers
        _write_state(folder, state)
        return script_revision(rows)


def _source_file(folder: Path, state: dict) -> Path | None:
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


def video_path(job_id: str) -> Path | None:
    """File video gốc của dự án, nếu còn trên máy."""
    found = _read_state(job_id)
    return _source_file(*found) if found else None


def audition_source(job_id):
    found = _read_state(job_id)
    if found:
        return _source_file(*found), float((found[1].get("info") or {}).get("duration") or 0)
    return None


def exists(job_id: str) -> bool:
    return (JOB_DIR / job_id / "state.json").is_file()


def thumbnail_sources(job_id: str) -> Iterator[Path]:
    """Try the original, then the newest video export belonging to this project."""
    found = _read_state(job_id)
    if not found:
        return
    roots = (JOB_DIR.resolve(), UPLOAD_DIR.resolve())

    def eligible(path: Path) -> bool:
        return (path.suffix.lower() in _PICTURE_VIDEO_EXT
                and any(path.resolve().is_relative_to(root) for root in roots))

    source = _source_file(*found)
    if source and eligible(source):
        yield source
    # Only scan render directories if the original is absent or cannot be decoded.
    newest = max((p for p in _output_paths(job_id) if p != source and eligible(p)),
                 key=lambda p: p.stat().st_mtime_ns, default=None)
    if newest:
        yield newest


def output_file(job_id: str, name: str) -> Path | None:
    """File kết quả để tải về. Chỉ nhận tên file trần, không nhận `../`."""
    wanted = Path(name).name
    for path in _output_paths(job_id):
        if path.name == wanted:
            return path
    return None


def delete(job_id: str, with_source: bool = False, *, source_owner_id=None) -> dict:
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
    films.unbind_job(job_id)
    characters.delete_for(job_id)
    with get_db() as db:
        db.query(JobScope).filter((JobScope.id == job_id) | (JobScope.parent_id == job_id)).delete()
        if upload_dir and source_owner_id is not None:
            owner = db.get(UploadOwner, upload_dir.name)
            if not owner or owner.member_id != source_owner_id:
                upload_dir = None

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
    return UPLOAD_DIR / rel.parts[0] if len(rel.parts) >= 2 else None


def _upload_in_use(upload_dir: Path) -> bool:
    """Còn dự án nào trỏ video vào thư mục upload này không."""
    target = upload_dir.resolve()
    for folder in JOB_DIR.iterdir():
        found = _read_state(folder.name)
        if not found:
            continue
        candidate = Path(found[1].get("video_path") or "")
        try:
            if candidate.resolve().is_relative_to(target):
                return True
        except (OSError, ValueError):
            continue
    return False
