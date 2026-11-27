"""Exercise real member sessions and separate libraries in a disposable studio."""
import io
import json
import sys
import wave
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack

import pytest
from fastapi.testclient import TestClient

import run
from backend import db
from backend.api import auth, deps, jobs, media
from backend.core import jobs as worker
from backend.main import app
from backend.store import films, projects


@pytest.fixture
def studio(tmp_db, workdir, monkeypatch):
    uploads, root = workdir / "uploads", workdir / "jobs"
    uploads.mkdir()
    root.mkdir()
    for mod in (projects, jobs, media, deps, worker):
        monkeypatch.setattr(mod, "JOB_DIR", root)
        if hasattr(mod, "UPLOAD_DIR"):
            monkeypatch.setattr(mod, "UPLOAD_DIR", uploads)
    monkeypatch.setattr(auth, "_attempts", type(auth._attempts)())
    with ExitStack() as stack:
        def account(name):
            c = stack.enter_context(TestClient(app, base_url="https://studio.test"))
            assert c.post("/api/auth/register", json={"username": name, "password": "local-test-password",
                          "invite": auth.issue_invite(), "role": "admin"}).status_code == 201
            assert c.get("/api/auth/me").json()["role"] == "member"
            return c
        yield account, root


def issue(c, kind, sid, role="viewer"):
    r = c.post(f"/api/collab/{kind}/{sid}/invites", json={"role": role})
    assert r.status_code == 201, r.text
    return r.json()["code"]


def join(c, code):
    return c.post("/api/collab/join", json={"code": code})


def wav_bytes():
    out = io.BytesIO()
    with wave.open(out, "wb") as f:
        f.setparams((1, 2, 8000, 0, "NONE", ""))
        f.writeframes(b"\0\0" * 8000)
    return out.getvalue()


def test_team_alone_is_not_project_access_and_removal_revokes_children(studio, monkeypatch):
    account, root = studio
    lead, editor, viewer = map(account, ("leader", "editor", "viewer"))
    tid = lead.post("/api/teams", json={"name": "Team A"}).json()["id"]
    fid = lead.post("/api/films", json={"name": "Film A", "team_id": tid}).json()["film"]["id"]
    assert editor.post("/api/films", json={"name": "Other", "team_id": tid}).status_code == 403
    pj = issue(lead, "films", fid, "editor")
    assert join(editor, auth.issue_invite()).status_code == 400
    assert viewer.post("/api/auth/register", json={"username":"not-registered", "password":"local-test-password",
                                                   "invite":pj}).status_code == 400
    assert join(editor, pj).status_code == 403
    tm = issue(lead, "teams", tid)
    assert join(editor, tm).is_success and join(viewer, tm).status_code == 400
    assert editor.get("/api/films").json()["films"] == []
    assert join(editor, pj).json()["role"] == "editor" and join(viewer, pj).status_code == 400
    assert editor.get("/api/films").json()["films"][0]["role"] == "editor"
    assert editor.post(f"/api/collab/films/{fid}/invites", json={"role":"editor"}).status_code == 403
    assert editor.post(f"/api/films/{fid}/episodes", json={"no": 1}).is_success
    media_id = editor.post("/api/upload", files={"file": ("qa.wav", wav_bytes(), "audio/wav")}).json()["media_id"]
    cfg = {"source_type":"file", "media_id":media_id, "film_id":fid, "episode_no":1, "sub_mode":"srt",
           "subtitle_text":"1\n00:00:00,100 --> 00:00:00,800\nXin chào.\n"}
    assert viewer.post("/api/analyze", json=cfg).status_code == 404
    monkeypatch.setattr(jobs, "run_in_thread", lambda job, target: target(job))
    jid = editor.post("/api/analyze", json=cfg).json()["job_id"]
    assert lead.get(f"/api/projects/{jid}/video", headers={"Range":"bytes=0-15"}).status_code == 206
    assert viewer.get("/api/projects").json()["projects"] == []
    assert viewer.get(f"/api/projects/{jid}/thumbnail").status_code == 404
    assert viewer.get(f"/api/films/{fid}/cover").status_code == 404
    assert join(viewer, issue(lead, "teams", tid)).is_success
    assert join(viewer, issue(lead, "films", fid)).is_success
    item = viewer.get(f"/api/projects/{jid}").json()
    assert item["role"] == "viewer" and item["cues"]
    assert viewer.post(f"/api/films/{fid}/cover?mode=auto").status_code == 403
    assert viewer.post(f"/api/projects/{jid}/cover?mode=auto").status_code == 403
    assert viewer.get(f"/api/media/{media_id}/stream").status_code == 404
    assert viewer.put(f"/api/projects/{jid}/cues", json={"cues":[]}).status_code == 403
    assert viewer.post(f"/api/jobs/{jid}/render", json={"outputs":{"srt":True}}).status_code == 403
    assert editor.delete(f"/api/projects/{jid}").status_code == 403
    assert editor.delete(f"/api/films/{fid}").status_code == 403
    rows = [{**item["cues"][0], "text2":"Bản A"}]
    save = editor.put(f"/api/projects/{jid}/cues", json={"revision":item["revision"], "cues":rows})
    assert save.is_success
    assert lead.put(f"/api/projects/{jid}/cues", json={"revision":item["revision"], "cues":[]}).status_code == 409
    rid = editor.post(f"/api/jobs/{jid}/render", json={"revision": save.json()["revision"],
                      "cues":[{**rows[0], "text2":"Bản duyệt"}], "outputs":{"srt":True}}).json()["job_id"]
    space = {"X-VSub-Project":jid}
    assert viewer.get("/api/translation-memory", headers=space).json()["pairs"] == 1
    assert viewer.delete("/api/translation-memory", headers=space).status_code == 403
    assert editor.get("/api/translation-memory").json()["pairs"] == 0
    output = next((root / rid).glob("*.srt")).name
    file = f"/api/jobs/{rid}/files/{output}"
    assert viewer.get(file).is_success
    eid = next(x["id"] for x in lead.get(f"/api/collab/films/{fid}").json()["members"] if x["username"] == "editor")
    assert lead.patch(f"/api/collab/films/{fid}/members/{eid}", json={"role":"viewer"}).is_success
    assert editor.post(f"/api/jobs/{rid}/cancel").status_code == 403
    assert lead.delete(f"/api/collab/teams/{tid}/members/{eid}").is_success
    for url in (file, f"/api/projects/{jid}", f"/api/jobs/{jid}", f"/api/projects/{jid}/files/{output}", f"/api/projects/{jid}/video"):
        assert editor.get(url).status_code == 404
    assert editor.get("/api/films").json()["films"] == []
    assert editor.get("/api/translation-memory", headers=space).status_code == 404
    assert join(editor, issue(lead, "teams", tid)).is_success
    assert editor.get(file).status_code == 404
    assert viewer.get(file).is_success
    assert lead.delete(f"/api/projects/{jid}?with_source=1").is_success
    assert editor.get(f"/api/media/{media_id}/stream").is_success


def test_invites_expiry_revoke_and_atomic_consumption(studio):
    account, _ = studio
    lead, a, b = map(account, ("leader", "first", "second"))
    fid = lead.post("/api/films", json={"name":"Personal"}).json()["film"]["id"]
    endpoint = f"/api/collab/films/{fid}"
    dead = issue(lead, "films", fid)
    pending = lead.get(endpoint).json()["invites"][0]
    assert "code" not in pending and "digest" not in pending
    assert lead.delete(f"{endpoint}/invites/{pending['id']}").is_success
    assert join(a, dead).status_code == 400
    expired = issue(lead, "films", fid)
    with db.get_db() as s:
        row = s.query(db.CollaborationInvite).one()
        assert row.digest == auth.digest(expired)
        row.expires = 1
    assert join(b, expired).status_code == 400
    code = issue(lead, "films", fid)
    with ThreadPoolExecutor(2) as pool:
        statuses = list(pool.map(lambda c: join(c, code).status_code, (a, b)))
    assert sorted(statuses) == [200, 400]
    assert len(lead.get(endpoint).json()["members"]) == 2


def test_admin_assignment_private_jobs_and_suspension(studio, monkeypatch):
    account, root = studio
    admin, lead, outsider = map(account, ("operator", "leader", "outsider"))
    old = films.create("Legacy")
    ep = films.add_episode(old["id"], 1)
    for jid in ("old-root", "old-loose"):
        (root / jid).mkdir()
        (root / jid / "state.json").write_text(json.dumps({"video_name":jid, "info":{}, "cues":[]}), encoding="utf-8")
    films.bind(old["id"], ep["no"], "old-root")
    assert admin.get("/api/films").json()["total_size"] == 0
    assert outsider.get("/api/admin/members").status_code == 403
    monkeypatch.setattr(sys, "argv", ["run.py", "--make-admin", "operator"])
    run.main()
    assert admin.get("/api/auth/me").json()["role"] == "admin"
    roster = admin.get("/api/admin/members").json()["members"]
    assert all("password_hash" not in p and "contact_email" not in p and "bio" not in p for p in roster)
    me = next(u for u in roster if u["self"])
    assert admin.patch(f"/api/admin/members/{me['id']}", json={"role":"member"}).status_code == 409
    assert outsider.post("/api/admin/invites").status_code == 403
    tid = lead.post("/api/teams", json={"name":"Production"}).json()["id"]
    assert admin.get("/api/films").json()["loose"][0]["id"] == "old-loose"
    assert admin.post(f"/api/admin/legacy/{old['id']}", json={"team_id":tid}).is_success
    assert lead.get("/api/projects/old-root").is_success
    assert lead.delete(f"/api/teams/{tid}").status_code == 409
    assert outsider.get("/api/projects/old-root").status_code == 404
    assert lead.post(f"/api/films/{old['id']}/episodes/1/bind", json={"job":"old-loose"}).status_code == 404
    uid = next(u["id"] for u in roster if u["username"] == "leader")
    assert admin.patch(f"/api/admin/members/{uid}", json={"active":False}).is_success
    assert lead.get("/api/auth/me").status_code == 401
    assert lead.post("/api/auth/login", json={"username":"leader","password":"local-test-password"}).status_code == 401
    assert admin.patch(f"/api/admin/members/{uid}", json={"active":True}).is_success
    assert lead.get("/api/auth/me").status_code == 401
    assert lead.post("/api/auth/login", json={"username":"leader","password":"local-test-password"}).is_success


def test_dissolve_empty_team_revokes_its_code(studio):
    account, _ = studio
    lead, outsider = map(account, ("leader", "outsider"))
    tid = lead.post("/api/teams", json={"name":"First name"}).json()["id"]
    assert lead.patch(f"/api/teams/{tid}", json={"name":"New name"}).is_success
    assert lead.get("/api/teams").json()["teams"][0]["name"] == "New name"
    code = issue(lead, "teams", tid)
    assert outsider.delete(f"/api/teams/{tid}").status_code == 404
    assert lead.delete(f"/api/teams/{tid}").is_success
    assert join(outsider, code).status_code == 400
