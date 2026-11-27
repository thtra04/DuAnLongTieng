"""One policy for the library, processing jobs, media and direct download routes."""
import re

from fastapi import Depends, HTTPException, Request
from sqlalchemy import and_, or_, select

from ..core import workspaces
from ..db import Episode, Film, FilmSeat, JobScope, TeamSeat, UploadOwner, get_db
from . import auth

LEVEL = {"viewer": 1, "editor": 2, "owner": 3}


def key(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", value):
        raise HTTPException(404, "Không tìm thấy tài nguyên.")
    return value


def require(role, minimum):
    if role not in LEVEL:
        raise HTTPException(404, "Không tìm thấy tài nguyên trong thư viện của bạn.")
    if LEVEL[role] < LEVEL[minimum]:
        raise HTTPException(403, "Vai trò hiện tại không cho phép thao tác này.")
    return role


def admin(user=Depends(auth.member)):
    if user["role"] != "admin":
        raise HTTPException(403, "Chỉ quản trị viên studio được thực hiện thao tác này.")
    return user


def film_roles(db, user, film_id=None):
    uid = user["id"]
    q = db.query(Film.id, Film.owner_id, FilmSeat.role).outerjoin(
        FilmSeat, and_(FilmSeat.film_id == Film.id, FilmSeat.member_id == uid))
    if film_id is not None:
        q = q.filter(Film.id == film_id)
    if user["role"] != "admin":
        q = q.filter(or_(Film.owner_id == uid, FilmSeat.role.is_not(None)),
                     or_(Film.team_id.is_(None), Film.team_id.in_(select(TeamSeat.team_id).where(TeamSeat.member_id == uid))))
    return {fid: "owner" if owner == uid or user["role"] == "admin" else role for fid, owner, role in q}


def film_role(db, user, film_id):
    return film_roles(db, user, key(film_id)).get(film_id)


def job_rights(db, user, job_id):
    """Return (role, root). Never infer ownership from user-supplied paths or JSON."""
    root = key(job_id)
    row = db.get(JobScope, root)
    if row and row.parent_id:
        root = row.parent_id
        row = db.get(JobScope, root)
    if user["role"] == "admin":
        return "owner", root
    fid = row.film_id if row else None
    if not fid:
        fid = db.query(Episode.film_id).filter_by(job=root).limit(1).scalar()
    if fid:
        return film_role(db, user, fid), root
    return ("owner" if row and row.owner_id == user["id"] else None), root


def library_ids(db, user):
    roles = film_roles(db, user)
    if user["role"] == "admin":
        return roles, None
    linked = db.query(Episode.job).filter(Episode.film_id.in_(roles), Episode.job.is_not(None))
    bound = select(Episode.job).where(Episode.job.is_not(None))
    scoped = db.query(JobScope.id).filter(JobScope.parent_id.is_(None), or_(
        JobScope.film_id.in_(roles), and_(JobScope.film_id.is_(None), JobScope.owner_id == user["id"],
                                         JobScope.id.not_in(bound))))
    return roles, {row[0] for row in linked.union(scoped)}


def upload_right(db, user, media_id):
    owner = db.get(UploadOwner, key(media_id))
    require("owner" if user["role"] == "admin" or (owner and owner.member_id == user["id"]) else None, "owner")


def record_job(job, user, *, parent=None, film=None):
    with get_db() as db:
        owner = user["id"]
        if film:
            require(film_role(db, user, film), "editor")
            owner = db.get(Film, film).owner_id
        db.add(JobScope(id=job.id, owner_id=None if parent else owner, film_id=film, parent_id=parent))


async def request_space(req: Request, user=Depends(auth.member)):
    scope = f"user-{user['id']}"
    job = req.path_params.get("job_id")
    selected = req.headers.get("x-vsub-project") if req.url.path in {
        "/api/ai/terms", "/api/translate-missing", "/api/translation-memory", "/api/translation-cache",
    } else None
    if job or selected:
        with get_db() as db:
            role, root = job_rights(db, user, job or selected)
        read = req.method == "GET" or req.url.path == "/api/ai/terms"
        require(role, "viewer" if read else "owner" if req.method == "DELETE" else "editor")
        if job and root != job and (req.url.path.startswith("/api/projects/") or
                                   req.url.path.endswith(("/render", "/retranslate"))):
            raise HTTPException(404, "Hãy mở dự án gốc.")
        scope = "project-" + root
    with workspaces.using(scope):
        yield
