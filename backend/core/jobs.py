"""Quản lý job chạy nền + tiến độ theo từng bước."""

from __future__ import annotations

import threading
import time
import traceback
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from ..config import JOB_DIR


@dataclass
class Step:
    key: str
    label: str
    weight: float = 1.0
    status: str = "pending"  # pending | running | done | skipped | error
    progress: float = 0.0
    detail: str = ""

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "label": self.label,
            "status": self.status,
            "progress": round(self.progress, 4),
            "detail": self.detail,
        }


@dataclass
class Job:
    id: str
    kind: str  # analyze | render | download
    status: str = "queued"  # queued | running | done | error | cancelled
    steps: list[Step] = field(default_factory=list)
    logs: list[str] = field(default_factory=list)
    error: str = ""
    result: dict = field(default_factory=dict)
    created: float = field(default_factory=time.time)
    updated: float = field(default_factory=time.time)
    cancel: threading.Event = field(default_factory=threading.Event, repr=False)

    # ------------------------------------------------------------ tiện ích
    @property
    def dir(self) -> Path:
        d = JOB_DIR / self.id
        d.mkdir(parents=True, exist_ok=True)
        return d

    def log(self, message: str) -> None:
        stamp = time.strftime("%H:%M:%S")
        self.logs.append(f"[{stamp}] {message}")
        if len(self.logs) > 400:
            del self.logs[:-400]
        self.updated = time.time()

    def step(self, key: str) -> Step | None:
        for s in self.steps:
            if s.key == key:
                return s
        return None

    def start_step(self, key: str, detail: str = "") -> None:
        s = self.step(key)
        if s:
            s.status = "running"
            s.progress = 0.0
            if detail:
                s.detail = detail
            self.updated = time.time()

    def set_step_progress(self, key: str, value: float, detail: str = "") -> None:
        s = self.step(key)
        if s:
            s.progress = max(0.0, min(1.0, value))
            if detail:
                s.detail = detail
            self.updated = time.time()

    def finish_step(self, key: str, detail: str = "") -> None:
        s = self.step(key)
        if s:
            s.status = "done"
            s.progress = 1.0
            if detail:
                s.detail = detail
            self.updated = time.time()

    def skip_step(self, key: str, detail: str = "") -> None:
        s = self.step(key)
        if s:
            s.status = "skipped"
            s.progress = 1.0
            s.detail = detail
            self.updated = time.time()

    @property
    def overall(self) -> float:
        total = sum(s.weight for s in self.steps) or 1.0
        done = sum(s.weight * (1.0 if s.status in ("done", "skipped") else s.progress) for s in self.steps)
        return round(min(1.0, done / total), 4)

    def check_cancel(self) -> None:
        if self.cancel.is_set():
            raise JobCancelled()

    def to_dict(self, include_logs: bool = True) -> dict:
        data = {
            "id": self.id,
            "kind": self.kind,
            "status": self.status,
            "progress": self.overall,
            "steps": [s.to_dict() for s in self.steps],
            "error": self.error,
            "result": self.result,
            "created": self.created,
            "updated": self.updated,
        }
        if include_logs:
            data["logs"] = self.logs[-120:]
        return data


class JobCancelled(RuntimeError):
    pass


_jobs: dict[str, Job] = {}
_jobs_lock = threading.Lock()


def create_job(kind: str, steps: list[Step], config: dict | None = None) -> Job:
    job = Job(id=uuid.uuid4().hex[:12], kind=kind, steps=steps)
    with _jobs_lock:
        _jobs[job.id] = job
        _prune()
    try:
        from .queue import get_queue

        get_queue().enqueue(job.id, kind, config or {})
    except Exception:
        pass
    return job


def get_job(job_id: str) -> Job | None:
    with _jobs_lock:
        return _jobs.get(job_id)


def _prune(keep: int = 60) -> None:
    if len(_jobs) <= keep:
        return
    ordered = sorted(_jobs.values(), key=lambda j: j.updated)
    for job in ordered[: len(_jobs) - keep]:
        if job.status in ("done", "error", "cancelled"):
            _jobs.pop(job.id, None)


def run_in_thread(job: Job, target) -> None:
    """Chạy `target(job)` trong thread nền, tự bắt lỗi."""

    def wrapper() -> None:
        job.status = "running"
        job.updated = time.time()
        # `status` luôn được đặt SAU CÙNG trong mỗi nhánh. Giao diện hỏi trạng
        # thái mỗi giây và dừng hỏi ngay khi thấy done/error/cancelled — đặt
        # status trước thì lần hỏi cuối có thể bắt được job đã lỗi mà bước vẫn
        # ghi "đang chạy", hoặc thiếu mất dòng log cuối.
        try:
            _sync_queue(job.id, "running")
            target(job)
            if job.status == "running":
                job.log("Hoàn tất.")
                job.status = "done"
                _sync_queue(job.id, "done")
        except JobCancelled:
            job.error = "Đã huỷ theo yêu cầu."
            job.log("Đã huỷ.")
            job.status = "cancelled"
            _sync_queue(job.id, "cancelled")
        except Exception as exc:
            job.error = str(exc) or exc.__class__.__name__
            job.log(f"LỖI: {job.error}")
            detail = traceback.format_exc(limit=6)
            for line in detail.strip().splitlines()[-6:]:
                job.log("  " + line)
            for s in job.steps:
                if s.status == "running":
                    s.status = "error"
            job.status = "error"
            _sync_queue(job.id, "error", error=job.error)
        finally:
            job.updated = time.time()

    threading.Thread(target=wrapper, daemon=True, name=f"job-{job.id}").start()


def _sync_queue(job_id: str, status: str, **extra) -> None:
    try:
        from .queue import get_queue

        get_queue().set_status(job_id, status, **extra)
    except Exception:
        pass
