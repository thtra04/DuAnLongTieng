"""Kho dữ liệu bộ phim & tập — SQLite qua SQLAlchemy (HP-7).

Trước đây lưu `data/films.json`; giờ dùng bảng ``films`` + ``episodes`` trong
``data/vsub.db``. File JSON cũ được migrate tự động khi khởi tạo DB (xem
``backend.db.init_db``).

Luồng đúng thứ tự:

    1. tạo bộ phim  ->  2. tạo tập  ->  3. đưa link / upload video cho tập đó
"""

from __future__ import annotations

import time
import uuid

from sqlalchemy import func

from ..db import Episode, Film, get_db

MAX_NAME = 160
MAX_EPISODES = 500


class FilmError(RuntimeError):
    pass


# ------------------------------------------------------------------ helpers


def _clean_name(name: str) -> str:
    name = " ".join(str(name or "").split())[:MAX_NAME]
    if not name:
        raise FilmError("Bộ phim phải có tên.")
    return name


# ------------------------------------------------------------------ bộ phim


def all_films() -> list[dict]:
    """Mọi bộ, mới tạo trước."""
    with get_db() as db:
        films = db.query(Film).order_by(Film.created.desc()).all()
        return [f.to_dict() for f in films]


def create(name: str, url: str = "", parts: list[dict] | None = None) -> dict:
    """Tạo bộ mới. `parts` (từ /api/link/inspect) thì tạo sẵn từng tập luôn."""
    with get_db() as db:
        # Mốc tạo phải tăng dần thì "mới tạo trước" mới chắc chắn: đồng hồ Windows
        # chỉ nhích ~15 ms một lần, hai bộ tạo liền nhau có thể trùng mốc và khi
        # đó thứ tự trên dưới là ngẫu nhiên.
        last = db.query(func.max(Film.created)).scalar() or 0.0
        film = Film(
            id=uuid.uuid4().hex[:8],
            name=_clean_name(name),
            url=(url or "").strip(),
            created=max(time.time(), last + 1e-3),
        )
        for index, part in enumerate(parts or [], 1):
            if len(film.episodes) >= MAX_EPISODES:
                break
            film.episodes.append(Episode(
                no=int(part.get("index") or index),
                title=" ".join(str(part.get("title") or "").split())[:MAX_NAME],
                duration=float(part.get("duration") or 0.0),
                job=None,
            ))
        db.add(film)
        db.flush()
        return film.to_dict()


def rename(film_id: str, name: str) -> dict:
    with get_db() as db:
        film = db.query(Film).filter_by(id=film_id).first()
        if not film:
            raise FilmError("Không tìm thấy bộ phim này.")
        film.name = _clean_name(name)
        db.flush()
        return film.to_dict()


def set_url(film_id: str, url: str) -> dict:
    with get_db() as db:
        film = db.query(Film).filter_by(id=film_id).first()
        if not film:
            raise FilmError("Không tìm thấy bộ phim này.")
        film.url = (url or "").strip()
        db.flush()
        return film.to_dict()


def remove(film_id: str) -> dict:
    """Bỏ bộ khỏi kho. Job của các tập thì bên gọi tự quyết định xoá hay không."""
    with get_db() as db:
        film = db.query(Film).filter_by(id=film_id).first()
        if not film:
            raise FilmError("Không tìm thấy bộ phim này.")
        result = film.to_dict()
        db.delete(film)
        return result


# --------------------------------------------------------------------- tập


def add_episode(film_id: str, no: int | None = None, title: str = "") -> dict:
    """Thêm một tập trống (chưa có video). Không truyền `no` thì lấy số kế tiếp."""
    with get_db() as db:
        film = db.query(Film).filter_by(id=film_id).first()
        if not film:
            raise FilmError("Không tìm thấy bộ phim này.")
        if len(film.episodes) >= MAX_EPISODES:
            raise FilmError(f"Một bộ tối đa {MAX_EPISODES} tập.")

        used = {ep.no for ep in film.episodes}
        if no is None:
            no = (max(used) + 1) if used else 1
        no = int(no)
        if no < 1:
            raise FilmError("Số tập phải từ 1 trở lên.")
        if no in used:
            raise FilmError(f"Bộ này đã có tập {no}.")

        episode = Episode(
            film_id=film_id,
            no=no,
            title=" ".join(str(title or "").split())[:MAX_NAME],
            duration=0.0,
            job=None,
        )
        db.add(episode)
        db.flush()
        return episode.to_dict()


def remove_episode(film_id: str, no: int) -> dict | None:
    """Bỏ một tập. Trả về tập đã bỏ (để bên gọi xoá job của nó nếu muốn)."""
    with get_db() as db:
        ep = (
            db.query(Episode)
            .filter_by(film_id=film_id, no=int(no))
            .first()
        )
        if not ep:
            return None
        result = ep.to_dict()
        db.delete(ep)
        return result


def bind(film_id: str, no: int, job_id: str) -> dict:
    """Gắn một job (đã phân tích xong) vào tập. Một job chỉ thuộc một tập."""
    with get_db() as db:
        # job đang gắn ở tập khác thì nhả ra trước
        old = db.query(Episode).filter_by(job=job_id).all()
        for ep in old:
            ep.job = None

        ep = db.query(Episode).filter_by(film_id=film_id, no=int(no)).first()
        if not ep:
            raise FilmError(f"Bộ này không có tập {no}.")
        ep.job = job_id
        db.flush()
        return ep.to_dict()


def unbind_job(job_id: str) -> bool:
    """Job bị xoá -> bỏ tham chiếu, để tập quay về trạng thái chưa có video."""
    with get_db() as db:
        eps = db.query(Episode).filter_by(job=job_id).all()
        if not eps:
            return False
        for ep in eps:
            ep.job = None
        return True


def bound_jobs() -> dict[str, tuple[str, int]]:
    """{job_id: (film_id, số tập)} — để biết job nào đã thuộc bộ nào."""
    with get_db() as db:
        eps = db.query(Episode).filter(Episode.job.isnot(None)).all()
        return {ep.job: (ep.film_id, ep.no) for ep in eps}
