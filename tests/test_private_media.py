"""Exercise private media over HTTP with a small, synthetic audio file."""

import io
import wave

import pytest

from backend.api import media


@pytest.fixture
def wav_upload(workdir, monkeypatch):
    monkeypatch.setattr(media, "UPLOAD_DIR", workdir)
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setparams((1, 2, 8000, 0, "NONE", "not compressed"))
        wav.writeframes(b"\0\0" * 800)
    return ("sample.wav", buffer.getvalue(), "audio/wav")


def test_private_audio_playback_before_and_after_logout(studio_client, wav_upload):
    uploaded = studio_client.post("/api/upload", files={"file": wav_upload})
    assert uploaded.status_code == 200, uploaded.text
    url = f"/api/media/{uploaded.json()['media_id']}/stream"
    original = wav_upload[1]

    full = studio_client.get(url)
    assert full.status_code == 200 and full.content == original
    assert "no-store" in full.headers["cache-control"]
    headers = {"Range": "bytes=4-11"}
    part = studio_client.get(url, headers=headers)
    assert part.status_code == 206 and part.content == original[4:12]
    assert part.headers["content-range"] == f"bytes 4-11/{len(original)}"
    assert "no-store" in part.headers["cache-control"]

    assert studio_client.post("/api/auth/logout").status_code == 200
    denied = studio_client.get(url, headers=headers)
    assert denied.status_code == 401
    assert "no-store" in denied.headers["cache-control"]


def test_over_limit_upload_leaves_no_partial_copy(studio_client, wav_upload, workdir, monkeypatch):
    monkeypatch.setattr(media, "MAX_UPLOAD_BYTES", len(wav_upload[1]) - 1)
    response = studio_client.post("/api/upload", files={"file": wav_upload})
    assert response.status_code == 413
    assert not any(workdir.iterdir())
