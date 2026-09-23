"""Kiểm thử lớp cơ sở dữ liệu SQLite / SQLAlchemy (HP-7).

Bao gồm: tạo bảng, quan hệ Film→Episode (cascade), Character→Voice, và
migrate tự động từ `films.json` cũ sang DB.
"""

from __future__ import annotations

import json

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from backend import db as db_mod
from backend.db import Base, Character, Episode, Film, Voice, get_db


@pytest.fixture(autouse=True)
def _db(tmp_db):
    """Mỗi test một DB riêng."""


# ------------------------------------------------------------ models


def test_tao_film_va_doc_lai():
    with get_db() as db:
        db.add(Film(id="abc12345", name="Bộ A", url="", created=1.0))
    with get_db() as db:
        film = db.query(Film).filter_by(id="abc12345").one()
        assert film.name == "Bộ A"
        assert film.episodes == []


def test_film_to_dict_kem_tap_sap_theo_so():
    with get_db() as db:
        film = Film(id="f1", name="Bộ", url="https://x", created=2.0)
        film.episodes.append(Episode(no=3, title="Ba"))
        film.episodes.append(Episode(no=1, title="Một"))
        db.add(film)
    with get_db() as db:
        data = db.query(Film).filter_by(id="f1").one().to_dict()
    assert data["id"] == "f1"
    assert data["url"] == "https://x"
    assert [e["no"] for e in data["episodes"]] == [1, 3]
    assert data["episodes"][0] == {"no": 1, "title": "Một", "duration": 0.0, "job": None}


def test_xoa_film_thi_tap_bi_xoa_theo():
    with get_db() as db:
        film = Film(id="f1", name="Bộ", created=1.0)
        film.episodes.append(Episode(no=1))
        film.episodes.append(Episode(no=2))
        db.add(film)
    with get_db() as db:
        db.delete(db.query(Film).filter_by(id="f1").one())
    with get_db() as db:
        assert db.query(Episode).count() == 0


def test_character_va_voice_quan_he_mot_mot():
    with get_db() as db:
        ch = Character(job_id="job1", speaker_label="S1", name="Nam chính", total_speech=42.5)
        ch.voice = Voice(voice_id="__clone__", style="tu_nhien", ref_path="/tmp/ref.wav")
        db.add(ch)
    with get_db() as db:
        ch = db.query(Character).filter_by(job_id="job1").one()
        assert ch.voice.voice_id == "__clone__"
        assert ch.voice.ref_path == "/tmp/ref.wav"
        assert ch.voice.character is ch


def test_xoa_character_thi_voice_bi_xoa_theo():
    with get_db() as db:
        ch = Character(job_id="job1", speaker_label="S1")
        ch.voice = Voice(voice_id="v1")
        db.add(ch)
    with get_db() as db:
        db.delete(db.query(Character).one())
    with get_db() as db:
        assert db.query(Voice).count() == 0


def test_get_db_rollback_khi_loi():
    with pytest.raises(RuntimeError):
        with get_db() as db:
            db.add(Film(id="f1", name="Bộ", created=1.0))
            raise RuntimeError("giả lỗi")
    with get_db() as db:
        assert db.query(Film).count() == 0


# ------------------------------------------------------------ init_db + migrate


@pytest.fixture
def kho_json(workdir, monkeypatch):
    """DB thật ở thư mục tạm + films.json cũ nằm cạnh để test migrate."""
    monkeypatch.setattr(db_mod, "DATA_DIR", workdir)
    monkeypatch.setattr(db_mod, "DB_PATH", workdir / "vsub.db")
    # init_db tự dựng engine từ DB_PATH — bỏ engine giả của tmp_db
    monkeypatch.setattr(db_mod, "_engine", None)
    monkeypatch.setattr(db_mod, "_SessionLocal", None)
    try:
        yield workdir
    finally:
        if db_mod._engine is not None:
            db_mod._engine.dispose()  # nhả file .db để workdir xoá được trên Windows


def test_init_db_tao_bang_khi_chua_co(kho_json):
    db_mod.init_db()
    assert (kho_json / "vsub.db").is_file()
    with get_db() as db:
        assert db.query(Film).count() == 0


def test_migrate_films_json_sang_db(kho_json):
    (kho_json / "films.json").write_text(
        json.dumps(
            {
                "films": [
                    {
                        "id": "old1",
                        "name": "Bộ cũ",
                        "url": "https://cu",
                        "created": 123.0,
                        "episodes": [
                            {"no": 2, "title": "Hai", "duration": 100.0, "job": "j2"},
                            {"no": 1, "title": "Một", "duration": 50.0, "job": None},
                        ],
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    db_mod.init_db()

    with get_db() as db:
        film = db.query(Film).filter_by(id="old1").one()
        assert film.name == "Bộ cũ"
        assert film.url == "https://cu"
        assert film.created == 123.0
        eps = {e.no: e for e in film.episodes}
        assert eps[2].job == "j2" and eps[2].duration == 100.0
        assert eps[1].job is None and eps[1].title == "Một"

    # file cũ được đổi tên để không migrate lại lần hai
    assert not (kho_json / "films.json").exists()
    assert (kho_json / "films.json.bak").is_file()


def test_khong_migrate_lai_khi_db_da_co_du_lieu(kho_json):
    db_mod.init_db()
    with get_db() as db:
        db.add(Film(id="keep", name="Đã có", created=1.0))

    (kho_json / "films.json").write_text(
        json.dumps({"films": [{"id": "new", "name": "Mới", "created": 2.0, "episodes": []}]}),
        encoding="utf-8",
    )
    db_mod.init_db()

    with get_db() as db:
        ids = {f.id for f in db.query(Film).all()}
    assert ids == {"keep"}
    assert (kho_json / "films.json").is_file(), "không đụng file khi bỏ qua migrate"


def test_migrate_bo_qua_json_hong(kho_json):
    (kho_json / "films.json").write_text("{ không phải json", encoding="utf-8")
    db_mod.init_db()  # không được nổ
    with get_db() as db:
        assert db.query(Film).count() == 0


def test_migrate_bo_qua_muc_thieu_id(kho_json):
    (kho_json / "films.json").write_text(
        json.dumps({"films": [{"name": "Không id", "episodes": []}, "rác", {"id": "ok", "name": "Có", "episodes": ["rác"]}]}),
        encoding="utf-8",
    )
    db_mod.init_db()
    with get_db() as db:
        assert [f.id for f in db.query(Film).all()] == ["ok"]
        assert db.query(Episode).count() == 0


def test_init_db_chay_hai_lan_khong_loi(kho_json):
    db_mod.init_db()
    db_mod.init_db()


def test_foreign_keys_duoc_bat(kho_json):
    """PRAGMA foreign_keys=ON: chèn tập trỏ tới film không tồn tại phải bị chặn."""
    from sqlalchemy.exc import IntegrityError

    db_mod.init_db()
    with pytest.raises(IntegrityError):
        with get_db() as db:
            db.add(Episode(film_id="khong-co", no=1))
