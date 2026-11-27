"""Project-private recordings that an editor actually auditioned (before timing/mix)."""

import hashlib
import json
import sqlite3
from contextlib import closing, contextmanager
from dataclasses import replace
from pathlib import Path

import numpy as np

from .dubbing import CLONE_VOICE, slot_frames
from .subtitles import shift_cues


def _digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


class AuditionTakes:
    def __init__(self, project_dir, video, cues):
        self.path = Path(project_dir) / ".auditions" / "takes.sqlite"
        source = Path(video) if video else None
        stamp = None
        if source and source.is_file():
            st = source.stat()
            stamp = [str(source.resolve()), st.st_size, st.st_mtime_ns]
        # A clone depends on the original recording and the selection of clean turns,
        # not the subtitle offset, translation, output mix or temporary reference filename.
        self.cast = _digest([stamp, [[c.start, c.end, c.speaker, c.text] for c in cues]])

    def key(self, unit, voice, style):
        fields = ["v3-take-1", unit["cues"], unit["text"], unit["speaker"], voice, style,
                  self.cast if voice == CLONE_VOICE else None]
        if unit.get("variant"):
            fields.append(unit["variant"])
        return _digest(fields)

    @contextmanager
    def _db(self):
        with closing(sqlite3.connect(self.path, timeout=10)) as db, db:
            db.execute("CREATE TABLE IF NOT EXISTS takes (id TEXT PRIMARY KEY, pcm BLOB NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS fits (id TEXT, room INTEGER, speed REAL, over REAL, "
                       "PRIMARY KEY(id,room,speed))")
            yield db

    def keys(self):
        if not self.path.is_file():
            return set()
        with self._db() as db:
            return {r[0] for r in db.execute("SELECT id FROM takes")}

    def read(self, key):
        if not self.path.is_file():
            return None
        with self._db() as db:
            row = db.execute("SELECT pcm FROM takes WHERE id=?", (key,)).fetchone()
        return np.frombuffer(row[0], dtype="<f4") if row else None

    def remember(self, key, audio):
        self.path.parent.mkdir(exist_ok=True)
        with self._db() as db:
            # Two open editors can audition the same line simultaneously. Both hear
            # the winner, not two different samples from the stochastic synthesizer.
            db.execute("INSERT OR IGNORE INTO takes VALUES (?,?)", (key, np.asarray(audio, dtype="<f4").tobytes()))
            return np.frombuffer(db.execute("SELECT pcm FROM takes WHERE id=?", (key,)).fetchone()[0], dtype="<f4")

    def record_fit(self, key, room, speed, over):
        with self._db() as db:
            db.execute("INSERT OR REPLACE INTO fits VALUES (?,?,?,?)", (key, room, speed, over))

    def bind(self, units, voices, voice, style, frozen=None):
        known = self.keys()
        for i, u in enumerate(units):
            key = self.key(u, voices.get(u["speaker"], voice), style)
            expected = frozen[i].get("take") if frozen is not None else u.get("take")
            if (expected and expected != key) or ((expected or u.get("variant")) and key not in known):
                raise ValueError(f"Dòng #{u['cues'][0] + 1}: không tìm thấy đúng bản thu đã chọn. "
                                 "Hãy tạo lượt đọc khác và duyệt lại; không tự thay bản thu.")
            if key in known:
                u["take"] = key

    def check_timing(self, cues, units, mix, duration):
        if not self.path.is_file():
            return
        with self._db() as db:
            bad = {(key, room): over for key, room, over in db.execute(
                "SELECT id,room,over FROM fits WHERE speed=? AND over>0", (mix["max_speed"],))}
        if not bad:
            return
        if mix["offset"]:
            cues = shift_cues([replace(c) for c in cues], mix["offset"])
        for u in units:
            key = self.key(u, mix["voices"].get(u["speaker"], mix["voice"]), mix["style"])
            over = bad.get((key, slot_frames(cues, u["cues"], duration)))
            if over:
                raise ValueError(f"Dòng #{u['cues'][0] + 1}: bản nghe thử vượt khung {over:.3f}s. "
                                 "Rút gọn lời, nới mốc hoặc tăng tốc tối đa rồi nghe lại.")
