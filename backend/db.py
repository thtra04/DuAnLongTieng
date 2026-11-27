"""Cơ sở dữ liệu quan hệ — SQLite qua SQLAlchemy (HP-7).

Bảng chính:
    Film       — bộ phim do người dùng tạo
    Episode    — tập phim, thuộc một Film
    Character  — nhân vật được phân đoạn (HP-1), thuộc một dự án/job
    Voice      — ánh xạ nhân vật → giọng TTS (HP-2)

Khởi tạo:
    from backend.db import get_db, init_db
    init_db()                        # tạo bảng + migrate JSON cũ
    with get_db() as db: ...         # dùng session
"""

from __future__ import annotations

import json
import logging
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    create_engine,
    event,
    inspect,
    text,
)
from sqlalchemy.orm import (
    DeclarativeBase,
    Session,
    column_property,
    declared_attr,
    mapped_column,
    relationship,
    sessionmaker,
)

from .config import DATA_DIR

log = logging.getLogger(__name__)

DB_PATH = DATA_DIR / "vsub.db"

_engine = None
_SessionLocal = None


class Base(DeclarativeBase):
    pass


# ------------------------------------------------------------------ models


class CoverFields:
    # Listing a library should read a boolean, never all its JPEGs.
    cover_jpeg = mapped_column(LargeBinary, nullable=True, deferred=True)

    @declared_attr
    def has_cover(cls):
        return column_property(cls.cover_jpeg.is_not(None))


class Film(CoverFields, Base):
    __tablename__ = "films"

    id = Column(String(8), primary_key=True)
    name = Column(String(160), nullable=False)
    url = Column(Text, default="")
    created = Column(Float, nullable=False)
    owner_id = Column(Integer, ForeignKey("studio_members.id"))
    team_id = Column(String(16), ForeignKey("teams.id"))

    episodes = relationship(
        "Episode",
        back_populates="film",
        cascade="all, delete-orphan",
        order_by="Episode.no",
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "url": self.url or "",
            "team_id": self.team_id,
            "legacy": self.owner_id is None,
            "created": self.created,
            **({"has_cover": True} if self.has_cover else {}),
            "episodes": [ep.to_dict() for ep in self.episodes],
        }


class Episode(CoverFields, Base):
    __tablename__ = "episodes"
    __table_args__ = (Index("uq_episode_number", "film_id", "no", unique=True),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    film_id = Column(String(8), ForeignKey("films.id", ondelete="CASCADE"), nullable=False)
    no = Column(Integer, nullable=False)
    title = Column(String(160), default="")
    duration = Column(Float, default=0.0)
    job = Column(String(32), nullable=True)

    film = relationship("Film", back_populates="episodes")

    def to_dict(self) -> dict:
        return {
            "no": self.no,
            "title": self.title or "",
            "duration": self.duration or 0.0,
            "job": self.job,
            **({"has_cover": True} if self.has_cover else {}),
        }


class Character(Base):
    """Nhân vật được phân đoạn người nói gán cho một dự án (HP-1)."""
    __tablename__ = "characters"
    __table_args__ = (Index("uq_character_label", "job_id", "speaker_label", unique=True),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    job_id = Column(String(32), nullable=False, index=True)
    speaker_label = Column(String(16), nullable=False)
    name = Column(String(160), default="")
    total_speech = Column(Float, default=0.0)
    # "M" | "F" | "" — đoán từ cao độ giọng (core/gender.py), người dùng sửa được
    gender = Column(String(1), default="")
    # Cao độ giọng gốc (Hz, trung vị) — để chọn giọng dựng sẵn gần giọng gốc nhất
    f0 = Column(Float, default=0.0)
    # "C" trẻ em | "A" người lớn | "E" cao tuổi | "" chưa rõ — trẻ em đoán từ cao độ, còn lại chọn tay
    age = Column(String(1), default="")

    voice = relationship(
        "Voice",
        back_populates="character",
        uselist=False,
        cascade="all, delete-orphan",
    )


class Voice(Base):
    """Ánh xạ nhân vật → giọng TTS (HP-2)."""
    __tablename__ = "voices"
    __table_args__ = (Index("uq_character_voice", "character_id", unique=True),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    character_id = Column(Integer, ForeignKey("characters.id", ondelete="CASCADE"), nullable=False)
    voice_id = Column(String(64), nullable=False)
    style = Column(String(32), default="tu_nhien")
    ref_path = Column(Text, nullable=True)

    character = relationship("Character", back_populates="voice")


class TranslationMemory(Base):
    """Bộ nhớ dịch: cặp câu (gốc → bản dịch) người dùng đã sửa tay và duyệt khi xuất."""
    __tablename__ = "translation_memory"

    id = Column(Integer, primary_key=True, autoincrement=True)
    # câu gốc đã chuẩn hoá (thường, gọn khoảng trắng, bỏ dấu câu cuối) — khoá tra cứu
    source_key = Column(String(400), nullable=False, index=True)
    source = Column(Text, nullable=False)
    target = Column(Text, nullable=False)
    source_lang = Column(String(12), default="")
    target_lang = Column(String(12), default="", index=True)
    job_id = Column(String(32), default="")
    scope = Column(String(96), nullable=False, server_default="")
    hits = Column(Integer, default=0)
    updated = Column(Float, default=0.0)


class Member(Base):
    __tablename__ = "studio_members"
    id = Column(Integer, primary_key=True)
    username = Column(String(48), nullable=False, unique=True)
    display_name = Column(String(80), nullable=False, server_default="")
    contact_email = Column(String(254), nullable=False, server_default="")
    crew_role = Column(String(80), nullable=False, server_default="")
    bio = Column(Text, nullable=False, server_default="")
    role = Column(String(12), nullable=False, server_default="member")
    active = Column(Boolean, nullable=False, server_default="1")
    password_hash = Column(String(200), nullable=False)
    created = Column(Float, nullable=False)


class LoginSession(Base):
    __tablename__ = "login_sessions"
    digest = Column(String(64), primary_key=True)
    member_id = Column(Integer, ForeignKey("studio_members.id", ondelete="CASCADE"), nullable=False, index=True)
    expires = Column(Float, nullable=False, index=True)


class StudioInvite(Base):
    __tablename__ = "studio_invites"
    digest = Column(String(64), primary_key=True)
    expires = Column(Float, nullable=False, index=True)


class Team(Base):
    __tablename__ = "teams"
    id = Column(String(16), primary_key=True)
    name = Column(String(100), nullable=False)
    owner_id = Column(Integer, ForeignKey("studio_members.id"), nullable=False)


class TeamSeat(Base):
    __tablename__ = "team_members"
    team_id = Column(String(16), ForeignKey("teams.id", ondelete="CASCADE"), primary_key=True)
    member_id = Column(Integer, ForeignKey("studio_members.id", ondelete="CASCADE"), primary_key=True)


class FilmSeat(Base):
    __tablename__ = "film_members"
    __table_args__ = (CheckConstraint("role IN ('viewer','editor')"),)
    film_id = Column(String(8), ForeignKey("films.id", ondelete="CASCADE"), primary_key=True)
    member_id = Column(Integer, ForeignKey("studio_members.id", ondelete="CASCADE"), primary_key=True)
    role = Column(String(12), nullable=False)


class CollaborationInvite(Base):
    __tablename__ = "collaboration_invites"
    __table_args__ = (CheckConstraint("(film_id IS NULL) <> (team_id IS NULL)"),)
    id = Column(String(16), primary_key=True)
    digest = Column(String(64), nullable=False, unique=True)
    team_id = Column(String(16), ForeignKey("teams.id", ondelete="CASCADE"))
    film_id = Column(String(8), ForeignKey("films.id", ondelete="CASCADE"))
    role = Column(String(12), nullable=False)
    expires = Column(Float, nullable=False)
    issuer_id = Column(Integer, ForeignKey("studio_members.id"), nullable=False)


class JobScope(CoverFields, Base):
    """Children (render/retranslate) follow the current rights of the root analysis."""
    __tablename__ = "job_scopes"
    id = Column(String(64), primary_key=True)
    owner_id = Column(Integer, ForeignKey("studio_members.id"))
    film_id = Column(String(8), ForeignKey("films.id", ondelete="SET NULL"), index=True)
    parent_id = Column(String(64), index=True)


class UploadOwner(Base):
    __tablename__ = "upload_owners"
    id = Column(String(64), primary_key=True)
    member_id = Column(Integer, ForeignKey("studio_members.id"), nullable=False)


# ------------------------------------------------------------------ engine


def _make_engine():
    url = f"sqlite:///{DB_PATH}"
    engine = create_engine(url, echo=False, future=True)

    @event.listens_for(engine, "connect")
    def _set_pragmas(dbapi_conn, _rec):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    return engine


def _get_engine():
    global _engine, _SessionLocal
    if _engine is None:
        _engine = _make_engine()
        _SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False)
    return _engine


@contextmanager
def get_db() -> Iterator[Session]:
    """Context manager cho một database session."""
    engine = _get_engine()
    session = _SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


# ------------------------------------------------------------------ init


def init_db() -> None:
    """Tạo bảng nếu chưa có và migrate dữ liệu JSON cũ."""
    engine = _get_engine()
    Base.metadata.create_all(engine)
    _add_missing_columns(engine)
    _migrate_json(engine)
    with engine.begin() as conn:
        # create_all skips indexes on existing tables. Never delete old duplicate rows to migrate.
        for model in (Episode, Character, Voice):
            for index in model.__table__.indexes:
                if index.unique:
                    index.create(conn, checkfirst=True)


def _add_missing_columns(engine) -> None:
    """Thêm cột mới vào bảng đã có từ bản trước (create_all không tự thêm cột)."""
    wanted = {
        "characters": {"gender": "VARCHAR(1) DEFAULT ''", "f0": "FLOAT DEFAULT 0",
                       "age": "VARCHAR(1) DEFAULT ''"},
        "studio_members": {"display_name": "VARCHAR(80) NOT NULL DEFAULT ''",
                           "contact_email": "VARCHAR(254) NOT NULL DEFAULT ''",
                           "crew_role": "VARCHAR(80) NOT NULL DEFAULT ''", "bio": "TEXT NOT NULL DEFAULT ''",
                           "role": "VARCHAR(12) NOT NULL DEFAULT 'member'", "active": "BOOLEAN NOT NULL DEFAULT 1"},
        "films": {"owner_id": "INTEGER REFERENCES studio_members(id)", "team_id": "VARCHAR(16) REFERENCES teams(id)",
                  "cover_jpeg": "BLOB"},
        "episodes": {"cover_jpeg": "BLOB"},
        "job_scopes": {"cover_jpeg": "BLOB"},
        "translation_memory": {"scope": "VARCHAR(96) NOT NULL DEFAULT ''"},
    }
    with engine.begin() as conn:
        for table, cols in wanted.items():
            have = {c["name"] for c in inspect(conn).get_columns(table)}
            for name, ddl in cols.items():
                if name not in have:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))


def _migrate_json(engine) -> None:
    """Nhập dữ liệu từ films.json nếu DB chưa có film nào."""
    json_path = DATA_DIR / "films.json"
    if not json_path.is_file():
        return

    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        count = session.query(Film).count()
        if count > 0:
            return

        try:
            data = json.loads(json_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        films_data = data.get("films") or []
        if not films_data:
            return

        for f in films_data:
            if not isinstance(f, dict) or not f.get("id"):
                continue
            film = Film(
                id=f["id"],
                name=f.get("name") or "(chưa đặt tên)",
                url=f.get("url") or "",
                created=float(f.get("created") or 0.0),
            )
            for ep in f.get("episodes") or []:
                if not isinstance(ep, dict):
                    continue
                film.episodes.append(Episode(
                    no=int(ep.get("no") or 0),
                    title=ep.get("title") or "",
                    duration=float(ep.get("duration") or 0.0),
                    job=ep.get("job"),
                ))
            session.add(film)

        session.commit()
        migrated = session.query(Film).count()
        log.info("Migrated %d films from films.json to SQLite", migrated)

        backup = json_path.with_suffix(".json.bak")
        json_path.rename(backup)
        log.info("Renamed films.json -> films.json.bak")
    except Exception:
        session.rollback()
        log.exception("Failed to migrate films.json")
    finally:
        session.close()
