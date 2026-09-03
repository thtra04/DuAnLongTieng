"""Kho dữ liệu bộ phim & tập — `data/films.json`.

Đây là **nguồn sự thật** về việc bạn đang làm những bộ nào, mỗi bộ có tập nào.
Luồng đúng thứ tự:

    1. tạo bộ phim  ->  2. tạo tập  ->  3. đưa link / upload video cho tập đó

Nên một tập tồn tại **trước khi** có video: `job` của nó là `None`. Khi nào chạy
xong phân tích thì mới gắn id job vào, và từ đó tập có phụ đề.

Trước đây tool đoán bộ phim từ link (mã BV, playlist…). Cách đó bỏ rồi vì video
upload từ máy không có link nào để mà đoán — chính là chỗ "không gộp lại được".
Giờ bộ phim do người dùng tạo, tool không đoán gì cả.
"""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path

from .config import DATA_DIR

STORE = DATA_DIR / "films.json"

MAX_NAME = 160
MAX_EPISODES = 500


class FilmError(RuntimeError):
    pass


# ------------------------------------------------------------------ đọc/ghi


def _load() -> dict:
    try:
        data = json.loads(STORE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"films": []}
    if not isinstance(data, dict) or not isinstance(data.get("films"), list):
        return {"films": []}
    return data


def _save(data: dict) -> None:
    STORE.parent.mkdir(parents=True, exist_ok=True)
    with STORE.open("w", encoding="utf-8", newline="") as fh:
        fh.write(json.dumps(data, ensure_ascii=False, indent=1))


def _find(data: dict, film_id: str) -> dict:
    for film in data["films"]:
        if film.get("id") == film_id:
            return film
    raise FilmError("Không tìm thấy bộ phim này.")


def _clean_name(name: str) -> str:
    name = " ".join(str(name or "").split())[:MAX_NAME]
    if not name:
        raise FilmError("Bộ phim phải có tên.")
    return name


# ------------------------------------------------------------------ bộ phim


def all_films() -> list[dict]:
    """Mọi bộ, mới tạo trước.

    Hai bộ tạo trong cùng một nhịp đồng hồ (Windows: ~15 ms) có `created` bằng
    nhau; chỉ sắp theo `created` thì sort ổn định giữ nguyên thứ tự chèn, tức
    bộ CŨ đứng trước. Lấy vị trí trong kho làm khoá phụ: chèn sau = mới hơn.
    """
    films = [f for f in _load()["films"] if isinstance(f, dict)]
    indexed = sorted(
        enumerate(films), key=lambda t: (t[1].get("created") or 0, t[0]), reverse=True
    )
    return [f for _, f in indexed]


def create(name: str, url: str = "", parts: list[dict] | None = None) -> dict:
    """Tạo bộ mới. `parts` (từ /api/link/inspect) thì tạo sẵn từng tập luôn."""
    data = _load()
    film = {
        "id": uuid.uuid4().hex[:8],
        "name": _clean_name(name),
        "url": (url or "").strip(),
        "created": time.time(),
        "episodes": [],
    }
    for index, part in enumerate(parts or [], 1):
        if len(film["episodes"]) >= MAX_EPISODES:
            break
        film["episodes"].append(
            {
                "no": int(part.get("index") or index),
                "title": " ".join(str(part.get("title") or "").split())[:MAX_NAME],
                "duration": float(part.get("duration") or 0.0),
                "job": None,
            }
        )
    data["films"].append(film)
    _save(data)
    return film


def rename(film_id: str, name: str) -> dict:
    data = _load()
    film = _find(data, film_id)
    film["name"] = _clean_name(name)
    _save(data)
    return film


def set_url(film_id: str, url: str) -> dict:
    data = _load()
    film = _find(data, film_id)
    film["url"] = (url or "").strip()
    _save(data)
    return film


def remove(film_id: str) -> dict:
    """Bỏ bộ khỏi kho. Job của các tập thì bên gọi tự quyết định xoá hay không."""
    data = _load()
    film = _find(data, film_id)
    data["films"] = [f for f in data["films"] if f.get("id") != film_id]
    _save(data)
    return film


# --------------------------------------------------------------------- tập


def add_episode(film_id: str, no: int | None = None, title: str = "") -> dict:
    """Thêm một tập trống (chưa có video). Không truyền `no` thì lấy số kế tiếp."""
    data = _load()
    film = _find(data, film_id)
    episodes = film.setdefault("episodes", [])
    if len(episodes) >= MAX_EPISODES:
        raise FilmError(f"Một bộ tối đa {MAX_EPISODES} tập.")

    used = {int(e.get("no") or 0) for e in episodes}
    if no is None:
        no = (max(used) + 1) if used else 1
    no = int(no)
    if no < 1:
        raise FilmError("Số tập phải từ 1 trở lên.")
    if no in used:
        raise FilmError(f"Bộ này đã có tập {no}.")

    episode = {
        "no": no,
        "title": " ".join(str(title or "").split())[:MAX_NAME],
        "duration": 0.0,
        "job": None,
    }
    episodes.append(episode)
    episodes.sort(key=lambda e: int(e.get("no") or 0))
    _save(data)
    return episode


def remove_episode(film_id: str, no: int) -> dict | None:
    """Bỏ một tập. Trả về tập đã bỏ (để bên gọi xoá job của nó nếu muốn)."""
    data = _load()
    film = _find(data, film_id)
    gone = None
    kept = []
    for episode in film.get("episodes") or []:
        if gone is None and int(episode.get("no") or 0) == int(no):
            gone = episode
        else:
            kept.append(episode)
    film["episodes"] = kept
    _save(data)
    return gone


def bind(film_id: str, no: int, job_id: str) -> dict:
    """Gắn một job (đã phân tích xong) vào tập. Một job chỉ thuộc một tập."""
    data = _load()
    film = _find(data, film_id)

    # job đang gắn ở tập khác thì nhả ra trước, tránh hiện hai nơi
    for other in data["films"]:
        for episode in other.get("episodes") or []:
            if episode.get("job") == job_id:
                episode["job"] = None

    for episode in film.get("episodes") or []:
        if int(episode.get("no") or 0) == int(no):
            episode["job"] = job_id
            _save(data)
            return episode
    raise FilmError(f"Bộ này không có tập {no}.")


def unbind_job(job_id: str) -> bool:
    """Job bị xoá -> bỏ tham chiếu, để tập quay về trạng thái chưa có video."""
    data = _load()
    changed = False
    for film in data["films"]:
        for episode in film.get("episodes") or []:
            if episode.get("job") == job_id:
                episode["job"] = None
                changed = True
    if changed:
        _save(data)
    return changed


def bound_jobs() -> dict[str, tuple[str, int]]:
    """{job_id: (film_id, số tập)} — để biết job nào đã thuộc bộ nào."""
    out: dict[str, tuple[str, int]] = {}
    for film in _load()["films"]:
        for episode in film.get("episodes") or []:
            job = episode.get("job")
            if job:
                out[str(job)] = (film.get("id") or "", int(episode.get("no") or 0))
    return out
