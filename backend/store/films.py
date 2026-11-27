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

from sqlalchemy import func, text
from sqlalchemy.exc import IntegrityError

from ..db import Episode, Film, JobScope, TeamSeat, get_db

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


def all_films(only_ids=None) -> list[dict]:
    """Mọi bộ, mới tạo trước."""
    with get_db() as db:
        q = db.query(Film)
        films = (q if only_ids is None else q.filter(Film.id.in_(only_ids))).order_by(Film.created.desc()).all()
        return [f.to_dict() for f in films]


def create(name: str, url: str = "", parts: list[dict] | None = None, *, owner_id=None, team_id=None) -> dict:
    """Tạo bộ mới. `parts` (từ /api/link/inspect) thì tạo sẵn từng tập luôn."""
    with get_db() as db:
        if team_id and not db.get(TeamSeat, (team_id, owner_id)):
            raise FilmError("Bạn chưa tham gia nhóm này.")
        # Mốc tạo phải tăng dần thì "mới tạo trước" mới chắc chắn: đồng hồ Windows
        # chỉ nhích ~15 ms một lần, hai bộ tạo liền nhau có thể trùng mốc và khi
        # đó thứ tự trên dưới là ngẫu nhiên.
        last = db.query(func.max(Film.created)).scalar() or 0.0
        film = Film(
            id=uuid.uuid4().hex[:8],
            name=_clean_name(name),
            owner_id=owner_id, team_id=team_id,
            url=(url or "").strip(),
            created=max(time.time(), last + 1e-3),
        )
        seen = set()
        for index, part in enumerate(parts or [], 1):
            if len(film.episodes) >= MAX_EPISODES:
                break
            no = int(part.get("index") or index)
            if no < 1 or no in seen:
                raise FilmError("Danh sách có số tập trùng hoặc không hợp lệ.")
            seen.add(no)
            film.episodes.append(Episode(
                no=no,
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
        for ep in film.episodes:
            if ep.job:
                _place_job(db, ep.job, None, film.owner_id)
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
        try:
            db.flush()
        except IntegrityError as exc:
            raise FilmError(f"Bộ này đã có tập {no}.") from exc
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
        if ep.job:
            _place_job(db, ep.job, None, ep.film.owner_id)
        db.delete(ep)
        return result


def _place_job(db, job_id, film_id, owner_id):
    scope = db.get(JobScope, job_id)
    if not scope:
        scope = JobScope(id=job_id)
        db.add(scope)
    scope.film_id, scope.owner_id = film_id, owner_id


def bind(film_id: str, no: int, job_id: str, *, only_empty=False) -> dict:
    """Gắn một job (đã phân tích xong) vào tập. Một job chỉ thuộc một tập."""
    with get_db() as db:
        if only_empty:
            db.execute(text("BEGIN IMMEDIATE"))
            existing = db.get(JobScope, job_id)
            if existing and (existing.parent_id or existing.film_id not in (None, film_id)):
                raise FilmError("Video đã thuộc dự án khác.")
        # job đang gắn ở tập khác thì nhả ra trước
        old = db.query(Episode).filter_by(job=job_id).all()
        if only_empty and any(ep.film_id != film_id or ep.no != int(no) for ep in old):
            raise FilmError("Video đã thuộc một tập khác.")
        for ep in old:
            ep.job = None

        ep = db.query(Episode).filter_by(film_id=film_id, no=int(no)).first()
        if not ep:
            raise FilmError(f"Bộ này không có tập {no}.")
        if only_empty and ep.job and ep.job != job_id:
            raise FilmError("Tập đã có video. Không ghi đè video hiện có.")
        if ep.job and ep.job != job_id:
            _place_job(db, ep.job, None, ep.film.owner_id)
        ep.job = job_id
        _place_job(db, job_id, film_id, ep.film.owner_id)
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
