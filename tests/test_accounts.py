"""Shared studio membership, session revocation, transport and non-destructive migration."""
import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

from backend import db
from backend.api import auth
from backend.main import app


@pytest.fixture
def web(tmp_db, monkeypatch):
    monkeypatch.setattr(auth, "_attempts", auth._attempts.copy())
    auth._attempts.clear()
    with TestClient(app, base_url="https://studio.test") as c:
        yield c


def test_invited_member_can_relogin_logout_and_expire(web):
    data = {"username": "Editor-1", "password": "dialogue-test-pass"}
    assert web.post("/api/auth/register", json=data).status_code == 400
    data["invite"] = auth.issue_invite()
    r = web.post("/api/auth/register", json=data)
    assert r.status_code == 201 and r.json() == {"username": "editor-1"}
    assert all(s in r.headers["set-cookie"] for s in ("HttpOnly", "Secure", "SameSite=strict"))
    films = web.get("/api/films")
    assert films.status_code == 200 and "no-store" in films.headers["cache-control"]
    assert web.post("/api/auth/register", json={**data, "username": "Editor-2"}).status_code == 400
    token = web.cookies.get(auth.COOKIE)
    with db.get_db() as s:
        assert data["password"] not in s.query(db.Member).one().password_hash
        assert s.query(db.LoginSession).one().digest == auth.digest(token)
    assert web.post("/api/auth/logout").status_code == 200
    web.cookies.set(auth.COOKIE, token)
    assert web.get("/api/auth/me").status_code == 401
    web.cookies.clear()
    assert web.post("/api/auth/login", json={**data, "password": "wrong-password"}).status_code == 401
    assert web.post("/api/auth/login", json=data).status_code == 200
    with db.get_db() as s:
        s.query(db.LoginSession).update({"expires": time.time() - 1})
    assert web.get("/api/auth/me").status_code == 401


def test_profile_name_is_private_to_member_and_login_name_is_stable(web):
    path = "/api/auth/me"
    edit = {"display_name": "  Biên tập Ánh  ", "username": "other", "crew_role": " Dựng phim ",
            "contact_email": "anh@example.com", "bio": "Phụ đề Việt.\r\nLồng tiếng."}
    assert web.patch(path, json=edit).status_code == 401
    for username in ("other", "editor"):
        web.cookies.clear()
        creds = {"username": username, "password": "studio-test-password"}
        assert web.post("/api/auth/register", json={**creds, "invite": auth.issue_invite()}).status_code == 201
    before = web.get(path).json()
    assert set(before) == {"username", "display_name", "created", "role", "contact_email", "crew_role", "bio"}
    assert before["created"] > 0
    assert before["role"] == "member"
    expected = {**before, "username": "editor", "display_name": "Biên tập Ánh", "crew_role": "Dựng phim",
                "contact_email": "anh@example.com", "bio": "Phụ đề Việt.\nLồng tiếng."}
    assert web.patch(path, json=edit).json() == expected
    assert web.patch(path, json={"display_name": "a"*81}).status_code == 400
    assert web.patch(path, json={"display_name": None}).status_code == 400
    for bad in ({"contact_email": "not-an-email"}, {"crew_role": "a\nb"}, {"bio": "a"*501}):
        assert web.patch(path, json={"display_name": "unsaved", **bad}).status_code == 400
    assert web.post("/api/auth/logout").status_code == 200
    assert web.post("/api/auth/login", json=creds).status_code == 200
    assert web.get(path).json() == expected
    assert web.patch(path, json={"display_name": ""}).json() == {**expected, "display_name": ""}
    with db.get_db() as s:
        other = s.query(db.Member).filter_by(username="other").one()
        assert (other.display_name, other.contact_email, other.crew_role, other.bio) == ("", "", "", "")
        other.role = "admin"
    assert web.post("/api/auth/login", json={**creds, "username": "other"}).status_code == 200
    directory = web.get("/api/admin/members").json()["members"]
    editor = next(m for m in directory if m["username"] == "editor")
    assert {"contact_email", "crew_role", "bio"}.isdisjoint(editor)


def test_password_change_requires_current_and_rotates_only_members_sessions(web):
    path = "/api/auth/password"
    creds = {"username": "editor", "password": "original-passphrase"}
    change = {"current_password": creds["password"], "new_password": "replacement-passphrase"}
    assert web.post(path, json=change).status_code == 401

    def enroll(name):
        web.cookies.clear()
        r = web.post("/api/auth/register", json={**creds, "username": name, "invite": auth.issue_invite()})
        assert r.status_code == 201
        return web.cookies.get(auth.COOKIE)

    unrelated = enroll("other")
    first = enroll("editor")
    web.cookies.clear()
    assert web.post("/api/auth/login", json=creds).status_code == 200
    second = web.cookies.get(auth.COOKIE)
    assert web.post(path, json={**change, "current_password": "incorrect-passphrase"}).status_code == 403
    for invalid in ("short", "a"*129, creds["password"]):
        assert web.post(path, json={**change, "new_password": invalid}).status_code == 400
    assert web.get("/api/auth/me").status_code == 200

    assert web.post(path, json=change).status_code == 200
    assert web.cookies.get(auth.COOKIE) not in (first, second)
    assert web.get("/api/auth/me").json()["username"] == "editor"
    for old in (first, second):
        assert web.get("/api/auth/me", headers={"Cookie": f"{auth.COOKIE}={old}"}).status_code == 401
    assert web.get("/api/auth/me", headers={"Cookie": f"{auth.COOKIE}={unrelated}"}).json()["username"] == "other"
    web.cookies.clear()
    assert web.post("/api/auth/login", json=creds).status_code == 401
    assert web.post("/api/auth/login", json={**creds, "password": change["new_password"]}).status_code == 200


def test_duplicate_account_rolls_back_invitation(web):
    info = {"username": "Editor", "password": "a password here", "invite": auth.issue_invite()}
    assert web.post("/api/auth/register", json=info).status_code == 201
    info.update(username="EDITOR", invite=auth.issue_invite())
    assert web.post("/api/auth/register", json=info).status_code == 409
    assert web.post("/api/auth/register", json={**info, "username":"Other"}).status_code == 201


def test_expired_invite_and_repeated_invalid_logins(web):
    data = {"invite":auth.issue_invite(), "username":"unknown", "password":"password-test"}
    with db.get_db() as s:
        s.query(db.StudioInvite).update({"expires": 1})
    assert web.post("/api/auth/register", json=data).status_code == 400
    for _ in range(14):
        assert web.post("/api/auth/login", json={}).status_code == 400
    assert web.post("/api/auth/login", json=data).status_code == 429


def test_library_files_and_mutations_require_membership(web):
    for path in ("/api/system", "/api/projects", "/api/films", "/api/media/123/stream",
                 "/api/projects/legacy/video", "/api/jobs/legacy/files/example.mp4"):
        assert web.get(path).status_code == 401
    assert web.post("/api/analyze", json={}).status_code == 401
    assert web.delete("/api/translation-memory").status_code == 401
    assert web.post("/api/auth/login", json={}, headers={"Origin":"https://other.test"}).status_code == 403
    assert web.post("http://studio.test/api/auth/register", json={}).status_code == 403


def test_database_upgrade_idempotent_with_existing_film(tmp_db):
    with db.get_db() as s:
        film = db.Film(id="sample", name="Before accounts", created=1)
        film.episodes.append(db.Episode(no=1, title="Original", job="legacy-job"))
        s.add(film)
    # The three account tables did not exist in the preceding release.
    for model in (db.LoginSession, db.StudioInvite, db.Member):
        model.__table__.drop(tmp_db)
    db.init_db()
    db.init_db()
    with db.get_db() as s:
        assert s.query(db.Film).one().episodes[0].job == "legacy-job"
        assert s.query(db.Member).count() == 0
    with pytest.raises(IntegrityError), db.get_db() as s:
        s.add(db.Episode(film_id="sample", no=1))


def test_terms_preview_does_not_write_or_replace_manual(studio_client):
    r = studio_client.post("/api/ai/terms", json={"source_lang":"zh", "target_lang":"vi",
        "texts":["我姓仇", "他去了重庆", "锦衣玉食"], "glossary":"重庆 = Tên tôi chọn"})
    assert [(x["zh"], x["vi"]) for x in r.json()["terms"]] == [("仇","Cừu"), ("锦衣玉食","ăn ngon mặc đẹp")]


def test_loopback_only_docker_publish_still_requires_membership(web, monkeypatch):
    monkeypatch.setenv("VSUB_LOOPBACK_PUBLISHED", "1")
    assert web.get("http://127.0.0.1/api/films").status_code == 401
    assert web.get("http://studio.test/api/films").status_code == 403
