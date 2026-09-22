"""Cấu hình chung cho bộ kiểm thử."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def workdir():
    """Thư mục tạm cho một test — thay cho `tmp_path` của pytest.

    Vì sao không dùng `tmp_path`: nó đi qua `make_numbered_dir_with_cleanup`,
    cơ chế đánh số + khoá + dọn thư mục cũ. Trên máy Windows này, mỗi lần lấy
    `tmp_path` mất **hơn 30 giây** trong khi `tempfile.mkdtemp()` thô chỉ mất
    dưới 1 ms (đo thật: 11 test dùng `tmp_path` ngốn ~350 giây, chính thân test
    chỉ chạy 0,03 giây). Bộ test mà chạy 6 phút thì không ai chạy nữa, nên ở
    đây tự tạo thư mục tạm và tự dọn.
    """
    path = Path(tempfile.mkdtemp(prefix="vsub-test-"))
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


@pytest.fixture(autouse=True, scope="session")
def _db_cach_ly():
    """Cả phiên test dùng DB tạm.

    Lifespan của app gọi `init_db()` — bất kỳ test nào mở `TestClient(app)` sẽ
    tạo bảng và migrate `films.json`. Không cách ly thì bộ test đụng thẳng vào
    `data/vsub.db` thật của người dùng.
    """
    from backend import db as db_mod

    path = Path(tempfile.mkdtemp(prefix="vsub-test-db-"))
    mp = pytest.MonkeyPatch()
    mp.setattr(db_mod, "DATA_DIR", path)
    mp.setattr(db_mod, "DB_PATH", path / "vsub.db")
    mp.setattr(db_mod, "_engine", None)
    mp.setattr(db_mod, "_SessionLocal", None)
    try:
        yield
    finally:
        if db_mod._engine is not None:
            db_mod._engine.dispose()
        mp.undo()
        shutil.rmtree(path, ignore_errors=True)


@pytest.fixture
def tmp_db(workdir, monkeypatch):
    """SQLite tạm cho mỗi test — không đụng DB thật."""
    from sqlalchemy import create_engine, event
    from sqlalchemy.orm import sessionmaker

    from backend import db as db_mod
    from backend.db import Base

    db_path = workdir / "test.db"
    engine = create_engine(f"sqlite:///{db_path}", echo=False, future=True)

    @event.listens_for(engine, "connect")
    def _fk(dbapi_conn, _rec):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)

    monkeypatch.setattr(db_mod, "_engine", engine)
    monkeypatch.setattr(db_mod, "_SessionLocal", session_factory)
