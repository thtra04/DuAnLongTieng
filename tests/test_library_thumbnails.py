import json
import subprocess
from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from backend.api import auth
from backend.core import media
from backend.main import app
from backend.store import projects


@pytest.fixture
def library(workdir, tmp_db, monkeypatch):
    jobs, uploads = workdir / "jobs", workdir / "uploads"
    (jobs / "scene").mkdir(parents=True)
    uploads.mkdir()
    monkeypatch.setattr(projects, "JOB_DIR", jobs)
    monkeypatch.setattr(projects, "UPLOAD_DIR", uploads)
    return jobs, uploads


def test_short_frame_and_export_after_source_removed(library, studio_client):
    jobs, uploads = library
    clip = uploads / "short.mp4"
    subprocess.run([media.ffmpeg_exe(), "-nostdin", "-v", "error", "-f", "lavfi", "-i",
                    "color=c=teal:s=160x90", "-frames:v", "1", "-c:v", "mpeg4", str(clip)],
                   check=True, capture_output=True, timeout=15)
    (jobs / "scene" / "state.json").write_text(json.dumps({"video_path": str(clip)}))
    url = "/api/projects/scene/thumbnail"
    first = studio_client.get(url)
    assert first.status_code == 200 and first.headers["content-type"] == "image/jpeg"
    assert first.content.startswith(b"\xff\xd8") and first.content.endswith(b"\xff\xd9")
    assert "no-store" in first.headers["cache-control"]

    render = jobs / "render"
    render.mkdir()
    (render / "render.json").write_text('{"source_job":"scene"}')
    clip.rename(render / "final.mp4")
    item = studio_client.get("/api/films").json()["loose"][0]
    assert item["has_thumbnail"] and not item["video_ok"]
    assert studio_client.get(url).content == first.content
    studio_client.cookies.clear()
    assert studio_client.get(url).status_code == 401


def test_text_only_and_unreadable_clip_have_no_thumbnail(library, studio_client):
    jobs, uploads = library
    clip = uploads / "sample.mp4"
    (jobs / "scene" / "state.json").write_text(json.dumps({"video_path": str(clip)}))
    assert not studio_client.get("/api/films").json()["loose"][0]["has_thumbnail"]
    for project in ("scene", "unknown"):
        assert studio_client.get(f"/api/projects/{project}/thumbnail").status_code == 404
    clip.write_bytes(b"incomplete clip")
    assert studio_client.get("/api/projects/scene/thumbnail").status_code == 404


def photo(color):
    out = BytesIO()
    Image.new("RGB", (960, 480), color).save(out, "PNG")
    return out.getvalue()


def test_custom_covers_are_independent_and_survive_a_bad_replacement(library, studio_client):
    jobs, _ = library
    (jobs / "scene" / "state.json").write_text("{}")
    c = studio_client
    fid = c.post("/api/films", json={"name": "Album"}).json()["film"]["id"]
    c.post(f"/api/films/{fid}/episodes", json={"no": 3}).raise_for_status()
    film = f"/api/films/{fid}/cover"
    episode, video = film + "?episode=3", "/api/projects/scene/cover"
    for url, color in [(film, "red"), (episode, "blue"), (video, "green")]:
        assert c.post(url, content=photo(color)).is_success
        r = c.get(url)
        assert r.is_success and "no-store" in r.headers["cache-control"]
        with Image.open(BytesIO(r.content)) as im:
            assert im.format == "JPEG" and im.size == (640, 320)
    before = c.get(episode).content
    assert before != c.get(film).content
    assert c.post(episode, content=b"not an image").status_code == 422
    assert c.post(episode, content=b"x" * (5 * 1024 * 1024 + 1)).status_code == 413
    assert c.get(episode).content == before
    assert c.post(film + "?episode=9", content=photo("red")).status_code == 404
    dash = c.get("/api/films").json()
    assert dash["films"][0]["has_cover"] and dash["films"][0]["episodes"][0]["has_cover"]
    assert dash["loose"][0]["has_cover"] and not dash["loose"][0]["has_thumbnail"]
    assert c.post(episode + "&mode=auto").is_success
    assert c.get(episode).status_code == 404 and c.get(film).is_success and c.get(video).is_success


def test_viewer_can_see_but_not_set_or_reset_covers(library, studio_client):
    c = studio_client
    jobs, _ = library
    (jobs / "scene" / "state.json").write_text("{}")
    fid = c.post("/api/films", json={"name": "Private album"}).json()["film"]["id"]
    c.post(f"/api/films/{fid}/episodes", json={"no": 1}).raise_for_status()
    c.post(f"/api/films/{fid}/episodes/1/bind", json={"job": "scene"}).raise_for_status()
    urls = [f"/api/films/{fid}/cover", f"/api/films/{fid}/cover?episode=1", "/api/projects/scene/cover"]
    img = photo("gold")
    for url in urls:
        c.post(url, content=img).raise_for_status()
    with TestClient(app, base_url="https://testserver") as reader:
        assert reader.get(urls[0]).status_code == 401
        reader.post("/api/auth/register", json={"username": "cover-reader", "password": "studio-test-pass",
                                                "invite": auth.issue_invite()}).raise_for_status()
        assert all(reader.get(url).status_code == 404 for url in urls)
        invite = c.post(f"/api/collab/films/{fid}/invites", json={"role": "viewer"}).json()["code"]
        reader.post("/api/collab/join", json={"code": invite}).raise_for_status()
        for url in urls:
            assert reader.get(url).is_success
            assert reader.post(url, content=img).status_code == 403
            assert reader.post(url, params={"mode": "auto"}).status_code == 403
