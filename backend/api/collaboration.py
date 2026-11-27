"""Account administration, teams, and opt-in access to individual film projects."""
import secrets
import time

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select, text

from ..db import CollaborationInvite, Film, FilmSeat, LoginSession, Member, Team, TeamSeat, get_db
from . import access, auth

router = APIRouter(prefix="/api", tags=["collaboration"])
ROLES = ("viewer", "editor")


def write_lock(db):
    # Serialize eligibility checks with consuming a code or revoking a membership.
    db.execute(text("BEGIN IMMEDIATE"))


def team_access(db, user, tid, manage=False):
    team = db.get(Team, tid)
    if not team or (user["role"] != "admin" and not db.get(TeamSeat, (tid, user["id"]))):
        raise HTTPException(404, "Không tìm thấy nhóm.")
    if manage and team.owner_id != user["id"] and user["role"] != "admin":
        raise HTTPException(403, "Chỉ trưởng nhóm hoặc quản trị viên được quản lý nhóm.")
    return team


def space(db, user, kind, sid, manage):
    if kind == "teams":
        return team_access(db, user, sid, manage)
    if kind == "films":
        access.require(access.film_role(db, user, sid), "owner" if manage else "viewer")
        return db.get(Film, sid)
    raise HTTPException(404, "Không tìm thấy không gian làm việc.")


def seat_model(kind):
    return (TeamSeat, TeamSeat.team_id) if kind == "teams" else (FilmSeat, FilmSeat.film_id)


def eligible_role(role):
    if role not in ROLES:
        raise HTTPException(400, "Chọn quyền chỉ xem hoặc biên tập.")
    return role


def team_name(payload):
    name = payload.get("name")
    if not isinstance(name, str) or not name.strip() or len(name.strip()) > 100 or not name.strip().isprintable():
        raise HTTPException(400, "Nhập tên nhóm từ 1 đến 100 ký tự trên một dòng.")
    return name.strip()


@router.get("/teams")
def teams(user=Depends(auth.member)):
    with get_db() as db:
        mine = {tid for tid, in db.query(TeamSeat.team_id).filter_by(member_id=user["id"])}
        q = db.query(Team).order_by(Team.name, Team.id)
        if user["role"] != "admin":
            q = q.filter(Team.id.in_(mine))
        return {"teams": [{"id": t.id, "name": t.name, "joined": t.id in mine,
                           "manage": t.owner_id == user["id"] or user["role"] == "admin"} for t in q]}


@router.post("/teams", status_code=201)
def create_team(payload: dict, user=Depends(auth.member)):
    with get_db() as db:
        team = Team(id=secrets.token_hex(8), name=team_name(payload), owner_id=user["id"])
        db.add(team)
        db.flush()
        db.add(TeamSeat(team_id=team.id, member_id=user["id"]))
        return {"id": team.id, "name": team.name}


@router.patch("/teams/{tid}")
def rename_team(tid: str, payload: dict, user=Depends(auth.member)):
    with get_db() as db:
        write_lock(db)
        team_access(db, user, tid, True).name = team_name(payload)
    return {"ok": True}


@router.delete("/teams/{tid}")
def dissolve_team(tid: str, user=Depends(auth.member)):
    with get_db() as db:
        write_lock(db)
        team = team_access(db, user, tid, True)
        if db.query(Film.id).filter_by(team_id=tid).first():
            raise HTTPException(409, "Nhóm còn dự án. Không thể giải tán hoặc tự xóa phim của nhóm.")
        db.delete(team)
    return {"ok": True}


@router.get("/collab/{kind}/{sid}")
def roster(kind: str, sid: str, user=Depends(auth.member)):
    with get_db() as db:
        obj = space(db, user, kind, sid, False)
        manager = user["role"] == "admin" or obj.owner_id == user["id"]
        model, col = seat_model(kind)
        rows = db.query(Member, model).join(model, model.member_id == Member.id).filter(col == sid).order_by(Member.username)
        people = [{"username": u.username, "name": u.display_name or u.username, "id": u.id,
                   "role": "owner" if u.id == obj.owner_id else getattr(seat, "role", "member")} for u, seat in rows]
        if kind == "films" and obj.owner_id:
            u = db.get(Member, obj.owner_id)
            people.insert(0, {"username": u.username, "name": u.display_name or u.username, "id": u.id, "role": "owner"})
        inv_col = CollaborationInvite.team_id if kind == "teams" else CollaborationInvite.film_id
        invites = db.query(CollaborationInvite).filter(inv_col == sid, CollaborationInvite.expires > time.time())
        return {"name": obj.name, "manage": manager, "members": people,
                "invites": [{"id": i.id, "role": i.role, "expires": i.expires} for i in invites] if manager else []}


@router.post("/collab/{kind}/{sid}/invites", status_code=201)
def invite(kind: str, sid: str, payload: dict, user=Depends(auth.member)):
    with get_db() as db:
        write_lock(db)
        space(db, user, kind, sid, True)
        team = kind == "teams"
        role = "member" if team else eligible_role(payload.get("role"))
        code = ("TM-" if team else "PJ-") + secrets.token_urlsafe(24)
        expires = time.time() + 86400
        db.add(CollaborationInvite(id=secrets.token_hex(8), digest=auth.digest(code), issuer_id=user["id"],
                                   team_id=sid if team else None, film_id=None if team else sid, role=role, expires=expires))
        return {"code": code, "expires": expires}


@router.delete("/collab/{kind}/{sid}/invites/{invite_id}")
def revoke_invite(kind: str, sid: str, invite_id: str, user=Depends(auth.member)):
    with get_db() as db:
        write_lock(db)
        space(db, user, kind, sid, True)
        col = CollaborationInvite.team_id if kind == "teams" else CollaborationInvite.film_id
        if not db.query(CollaborationInvite).filter(col == sid, CollaborationInvite.id == invite_id).delete():
            raise HTTPException(404, "Mã mời không còn hiệu lực.")
    return {"ok": True}


@router.post("/collab/join")
def join(payload: dict, request: Request, user=Depends(auth.member)):
    auth.throttle(request)
    code = payload.get("code")
    invalid = HTTPException(400, "Mã cộng tác không hợp lệ, đã dùng hoặc đã hết hạn.")
    if not isinstance(code, str) or len(code) > 128:
        raise invalid
    with get_db() as db:
        write_lock(db)
        i = db.query(CollaborationInvite).filter_by(digest=auth.digest(code.strip())).first()
        if not i or i.expires <= time.time():
            raise invalid
        issuer = db.get(Member, i.issuer_id)
        if not issuer.active:
            raise invalid
        kind, sid = ("teams", i.team_id) if i.team_id else ("films", i.film_id)
        obj = db.get(Team if i.team_id else Film, sid)
        if issuer.role != "admin" and issuer.id != obj.owner_id:
            raise invalid
        uid = user["id"]
        model, _ = seat_model(kind)
        if i.film_id and obj.team_id and not db.get(TeamSeat, (obj.team_id, uid)):
            raise HTTPException(403, "Bạn phải tham gia đúng nhóm trước khi dùng mã dự án. Mã chưa bị dùng.")
        if db.get(model, (sid, uid)) or uid == obj.owner_id:
            raise HTTPException(409, "Bạn đã là thành viên. Mã chưa bị dùng.")
        db.add(TeamSeat(team_id=sid, member_id=uid) if i.team_id else FilmSeat(film_id=sid, member_id=uid, role=i.role))
        db.delete(i)
        return {"kind": kind, "id": sid, "name": obj.name, "role": i.role}


@router.patch("/collab/films/{sid}/members/{uid}")
def change_film_role(sid: str, uid: int, payload: dict, user=Depends(auth.member)):
    role = eligible_role(payload.get("role"))
    with get_db() as db:
        write_lock(db)
        space(db, user, "films", sid, True)
        seat = db.get(FilmSeat, (sid, uid))
        if not seat:
            raise HTTPException(404, "Không tìm thấy cộng tác viên.")
        seat.role = role
    return {"ok": True}


@router.delete("/collab/{kind}/{sid}/members/{uid}")
def remove_member(kind: str, sid: str, uid: int, user=Depends(auth.member)):
    with get_db() as db:
        write_lock(db)
        obj = space(db, user, kind, sid, True)
        if uid == obj.owner_id:
            raise HTTPException(409, "Không thể gỡ chủ sở hữu.")
        model, _ = seat_model(kind)
        seat = db.get(model, (sid, uid))
        if not seat:
            raise HTTPException(404, "Không tìm thấy thành viên.")
        if kind == "teams":
            if db.query(Film.id).filter_by(team_id=sid, owner_id=uid).first():
                raise HTTPException(409, "Thành viên đang sở hữu dự án trong nhóm này.")
            db.query(FilmSeat).filter(FilmSeat.member_id == uid, FilmSeat.film_id.in_(
                select(Film.id).where(Film.team_id == sid))).delete(synchronize_session=False)
        db.delete(seat)
    return {"ok": True}


@router.get("/admin/members")
def directory(user=Depends(access.admin)):
    with get_db() as db:
        memberships = {}
        for uid, name in db.query(TeamSeat.member_id, Team.name).join(Team, Team.id == TeamSeat.team_id):
            memberships.setdefault(uid, []).append(name)
        return {"members": [{**auth.public_profile(m), "id": m.id, "active": m.active,
                             "teams": memberships.get(m.id, []), "self": m.id == user["id"]}
                            for m in db.query(Member).order_by(Member.username)]}


@router.post("/admin/invites", status_code=201)
def registration_invite(_=Depends(access.admin)):
    return {"code": auth.issue_invite()}


@router.patch("/admin/members/{uid}")
def update_member(uid: int, payload: dict, user=Depends(access.admin)):
    if not payload or set(payload) - {"role", "active"} or ("role" in payload and payload["role"] not in ("admin", "member")) or (
            "active" in payload and not isinstance(payload["active"], bool)):
        raise HTTPException(400, "Quyền hoặc trạng thái tài khoản không hợp lệ.")
    if uid == user["id"]:
        raise HTTPException(409, "Không thể thay đổi quyền hoặc khóa chính mình tại đây.")
    with get_db() as db:
        write_lock(db)
        actor = db.get(Member, user["id"])
        if not actor.active or actor.role != "admin":
            raise HTTPException(403, "Quyền quản trị đã thay đổi.")
        target = db.get(Member, uid)
        if not target:
            raise HTTPException(404, "Không tìm thấy tài khoản.")
        target.role = payload.get("role", target.role)
        target.active = payload.get("active", target.active)
        if not target.active:
            db.query(LoginSession).filter_by(member_id=uid).delete()
            db.query(CollaborationInvite).filter_by(issuer_id=uid).delete()
    return {"ok": True}


@router.post("/admin/legacy/{film_id}")
def assign_legacy(film_id: str, payload: dict, user=Depends(access.admin)):
    with get_db() as db:
        write_lock(db)
        film = db.get(Film, film_id)
        if not film or film.owner_id is not None:
            raise HTTPException(409, "Dự án không còn ở kho chưa phân công.")
        team = db.get(Team, payload.get("team_id")) if isinstance(payload.get("team_id"), str) else None
        if not team:
            raise HTTPException(400, "Hãy chọn nhóm nhận dự án.")
        if db.query(FilmSeat).filter_by(film_id=film.id).first():
            raise HTTPException(409, "Gỡ các cộng tác viên cũ trước khi chuyển dự án.")
        db.query(CollaborationInvite).filter_by(film_id=film.id).delete()
        film.team_id, film.owner_id = team.id, team.owner_id
        return {"ok": True}
