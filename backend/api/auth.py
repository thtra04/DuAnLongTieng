"""Studio registration, profiles and revocable sessions."""
from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
import threading
import time
from collections import OrderedDict

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.exc import IntegrityError

from ..db import LoginSession, Member, StudioInvite, get_db

router = APIRouter(prefix="/api/auth", tags=["accounts"])
COOKIE = "vsub_session"
LIFETIME = 7 * 86400
PROFILE_FIELDS = {
    "display_name": ("Tên hiển thị", 80),
    "contact_email": ("Email liên hệ", 254),
    "crew_role": ("Công việc trong ê-kíp", 80),
    "bio": ("Giới thiệu", 500),
}
_lock = threading.Lock()
_attempts = OrderedDict()


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def password_hash(password, salt):
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 600_000).hex()


def encode_password(password):
    salt = secrets.token_hex(16)
    return f"{salt}:{password_hash(password, salt)}"


def password_matches(password, stored):
    salt, expected = stored.split(":") if stored else ("0"*32, "0"*64)
    return hmac.compare_digest(password_hash(password, salt), expected)


def issue_invite():
    token = secrets.token_urlsafe(24)
    with get_db() as db:
        db.query(StudioInvite).filter(StudioInvite.expires <= time.time()).delete()
        db.add(StudioInvite(digest=digest(token), expires=time.time() + 86400))
    return token


def transport(req: Request):
    host = req.url.hostname
    if req.url.scheme != "https" and not (
        host in ("localhost", "127.0.0.1", "::1") and req.client
        and (req.client.host in ("127.0.0.1", "::1") or os.getenv("VSUB_LOOPBACK_PUBLISHED") == "1")
    ):
        raise HTTPException(403, "Dùng HTTPS khi kết nối qua mạng, hoặc dùng localhost qua USB.")
    if req.method not in ("GET", "HEAD", "OPTIONS"):
        origin = req.headers.get("origin")
        allowed = {str(req.base_url).rstrip("/"), *(s.strip() for s in os.getenv("VSUB_CORS_ORIGINS", "").split(",") if s.strip())}
        if (origin and origin not in allowed) or (not origin and req.headers.get("sec-fetch-site") == "cross-site"):
            raise HTTPException(403, "Nguồn gửi yêu cầu không hợp lệ.")


def session_member(req, db):
    token = req.cookies.get(COOKIE, "")
    if token and len(token) <= 100:
        row = (db.query(Member).join(LoginSession).filter(Member.active.is_(True), LoginSession.digest == digest(token),
               LoginSession.expires > time.time()).first())
        if row:
            return row
    raise HTTPException(401, "Hãy đăng nhập vào studio.")


def public_profile(user):
    return {"username": user.username, "display_name": user.display_name, "created": user.created, "role": user.role}


def own_profile(user):
    # Contact details and biography are not part of the studio's member directory.
    return {**public_profile(user), "contact_email": user.contact_email, "crew_role": user.crew_role, "bio": user.bio}


def member(req: Request, _=Depends(transport)):
    with get_db() as db:
        user = session_member(req, db)
        return {**public_profile(user), "id": user.id}


def throttle(req):
    host = req.client.host if req.client else ""
    now = time.monotonic()
    with _lock:
        count, end = _attempts.pop(host, (0, now + 120))
        if now >= end:
            count, end = 0, now + 120
        _attempts[host] = (count + 1, end)
        if len(_attempts) > 4096:
            _attempts.popitem(last=False)
        if count >= 15:
            raise HTTPException(429, "Quá nhiều lần thử. Vui lòng đợi hai phút.")


def valid_password(pw):
    if not isinstance(pw, str) or not 10 <= len(pw) <= 128:
        raise HTTPException(400, "Mật khẩu cần từ 10 đến 128 ký tự.")
    return pw


def credentials(data):
    name = data.get("username")
    if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{3,48}", name.strip()):
        raise HTTPException(400, "Tên tài khoản: 3–48 ký tự không dấu, số, dấu chấm, gạch nối hoặc gạch dưới.")
    return name.strip().lower(), valid_password(data.get("password"))


def start_session(req, res, db, user):
    token = secrets.token_urlsafe(32)
    old = req.cookies.get(COOKIE, "")
    db.query(LoginSession).filter((LoginSession.expires <= time.time()) |
                                  (LoginSession.digest == digest(old))).delete()
    # Under the SQLite write lock, don't issue a session for a concurrently replaced password.
    if not db.query(Member.id).filter_by(id=user.id, active=True, password_hash=user.password_hash).first():
        raise HTTPException(409, "Mật khẩu vừa thay đổi. Vui lòng đăng nhập lại.")
    db.add(LoginSession(digest=digest(token), member_id=user.id, expires=time.time() + LIFETIME))
    res.set_cookie(COOKIE, token, max_age=LIFETIME, httponly=True, secure=req.url.scheme == "https", samesite="strict")
    res.headers["Cache-Control"] = "no-store"
    return {"username": user.username}


@router.post("/register", status_code=201, dependencies=[Depends(transport)])
def register(payload: dict, request: Request, response: Response):
    throttle(request)
    name, pw = credentials(payload)
    invite = payload.get("invite")
    if not isinstance(invite, str) or len(invite) > 128:
        raise HTTPException(400, "Mã mời không hợp lệ hoặc đã hết hạn.")
    try:
        with get_db() as db:
            # Consuming the invitation and creating the member commit together.
            consumed = db.query(StudioInvite).filter(StudioInvite.digest == digest(invite.strip()),
                                                     StudioInvite.expires > time.time()).delete()
            if not consumed:
                raise HTTPException(400, "Mã mời không hợp lệ hoặc đã hết hạn.")
            user = Member(username=name, password_hash=encode_password(pw), created=time.time())
            db.add(user)
            db.flush()
            return start_session(request, response, db, user)
    except IntegrityError as exc:
        raise HTTPException(409, "Tên tài khoản đã được sử dụng.") from exc


@router.post("/login", dependencies=[Depends(transport)])
def login(payload: dict, request: Request, response: Response):
    throttle(request)
    name, pw = credentials(payload)
    with get_db() as db:
        user = db.query(Member).filter_by(username=name).one_or_none()
        if not password_matches(pw, user.password_hash if user else None) or not user or not user.active:
            raise HTTPException(401, "Tên tài khoản hoặc mật khẩu không đúng.")
        return start_session(request, response, db, user)


@router.get("/me", dependencies=[Depends(transport)])
def me(request: Request, response: Response):
    response.headers["Cache-Control"] = "no-store"
    with get_db() as db:
        return own_profile(session_member(request, db))


@router.patch("/me", dependencies=[Depends(transport)])
def update_profile(payload: dict, request: Request):
    with get_db() as db:
        user = session_member(request, db)
        if PROFILE_FIELDS.keys().isdisjoint(payload):
            raise HTTPException(400, "Không có thông tin hồ sơ để cập nhật.")
        for key, (label, limit) in PROFILE_FIELDS.items():
            if key not in payload:
                continue
            value = payload[key]
            if not isinstance(value, str):
                raise HTTPException(400, f"{label} phải là văn bản.")
            value = value.strip().replace("\r\n", "\n")
            text = value.replace("\n", "") if key == "bio" else value
            if len(value) > limit or (text and not text.isprintable()):
                raise HTTPException(400, f"{label} không hợp lệ (tối đa {limit} ký tự).")
            if key == "contact_email" and value and not re.fullmatch(r"[^@\s<>]+@[^@\s<>]+\.[^@\s<>]+", value):
                raise HTTPException(400, "Email liên hệ chưa đúng định dạng (ví dụ: ban@example.com).")
            setattr(user, key, value)
        return own_profile(user)


@router.post("/password", dependencies=[Depends(transport)])
def change_password(payload: dict, request: Request, response: Response):
    with get_db() as db:
        user = session_member(request, db)
        throttle(request)
        current = payload.get("current_password")
        new = valid_password(payload.get("new_password"))
        if (not isinstance(current, str) or not 10 <= len(current) <= 128
                or not password_matches(current, user.password_hash)):
            raise HTTPException(403, "Mật khẩu hiện tại không đúng.")
        if new == current:
            raise HTTPException(400, "Mật khẩu mới phải khác mật khẩu hiện tại.")
        changed = db.query(Member).filter_by(id=user.id, password_hash=user.password_hash).update(
            {Member.password_hash: encode_password(new)})
        if not changed:
            raise HTTPException(409, "Mật khẩu vừa thay đổi. Vui lòng thử lại.")
        db.query(LoginSession).filter_by(member_id=user.id).delete()
        return start_session(request, response, db, user)


@router.post("/logout", dependencies=[Depends(transport)])
def logout(request: Request, response: Response):
    with get_db() as db:
        db.query(LoginSession).filter_by(digest=digest(request.cookies.get(COOKIE, ""))).delete()
    response.delete_cookie(COOKIE, httponly=True, secure=request.url.scheme == "https", samesite="strict")
    return {"ok": True}
