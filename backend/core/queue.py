"""Hàng đợi tác vụ — Redis khi có, in-memory khi không (HP-7).

Lớp trừu tượng ``JobQueue`` cho phép hệ thống:
    - Đẩy job vào hàng đợi
    - Lưu trạng thái job qua các lần khởi động lại (Redis)
    - Fallback sang dict Python khi Redis không khả dụng

Sử dụng:
    from backend.core.queue import get_queue
    q = get_queue()
    q.enqueue(job_id, kind, config)
    q.set_status(job_id, "running")
    info = q.get_status(job_id)
"""

from __future__ import annotations

import json
import logging
import os
import time
from abc import ABC, abstractmethod

log = logging.getLogger(__name__)

REDIS_URL = os.environ.get("VSUB_REDIS_URL", "redis://localhost:6379/0")
_KEY_PREFIX = "vsub:job:"
_QUEUE_KEY = "vsub:queue"


class JobQueue(ABC):
    """Giao diện hàng đợi tác vụ."""

    @abstractmethod
    def enqueue(self, job_id: str, kind: str, config: dict) -> None:
        """Đẩy một job mới vào hàng đợi."""

    @abstractmethod
    def dequeue(self) -> tuple[str, str, dict] | None:
        """Lấy job tiếp theo. Trả (job_id, kind, config) hoặc None."""

    @abstractmethod
    def set_status(self, job_id: str, status: str, **extra) -> None:
        """Cập nhật trạng thái job."""

    @abstractmethod
    def get_status(self, job_id: str) -> dict | None:
        """Đọc trạng thái job."""

    @abstractmethod
    def list_jobs(self, limit: int = 50) -> list[dict]:
        """Liệt kê các job gần đây."""

    @abstractmethod
    def cleanup(self, max_age: int = 86400) -> int:
        """Dọn job cũ. Trả số lượng đã xoá."""


class RedisQueue(JobQueue):
    """Hàng đợi Redis — job sống qua restart, hỗ trợ nhiều worker."""

    def __init__(self, url: str = REDIS_URL):
        import redis

        self._r = redis.from_url(url, decode_responses=True)
        self._r.ping()
        log.info("Redis queue connected: %s", url)

    def enqueue(self, job_id: str, kind: str, config: dict) -> None:
        data = {
            "id": job_id,
            "kind": kind,
            "config": json.dumps(config, ensure_ascii=False),
            "status": "queued",
            "created": time.time(),
            "updated": time.time(),
        }
        self._r.hset(_KEY_PREFIX + job_id, mapping=data)
        self._r.lpush(_QUEUE_KEY, job_id)

    def dequeue(self) -> tuple[str, str, dict] | None:
        job_id = self._r.rpop(_QUEUE_KEY)
        if not job_id:
            return None
        info = self.get_status(job_id)
        if not info:
            return None
        return job_id, info.get("kind", ""), json.loads(info.get("config", "{}"))

    def set_status(self, job_id: str, status: str, **extra) -> None:
        update = {"status": status, "updated": time.time()}
        for k, v in extra.items():
            update[k] = json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else str(v)
        self._r.hset(_KEY_PREFIX + job_id, mapping=update)

    def get_status(self, job_id: str) -> dict | None:
        data = self._r.hgetall(_KEY_PREFIX + job_id)
        return data if data else None

    def list_jobs(self, limit: int = 50) -> list[dict]:
        keys = self._r.keys(_KEY_PREFIX + "*")
        jobs = []
        for key in keys[:limit * 2]:
            data = self._r.hgetall(key)
            if data:
                jobs.append(data)
        jobs.sort(key=lambda j: float(j.get("updated", 0)), reverse=True)
        return jobs[:limit]

    def cleanup(self, max_age: int = 86400) -> int:
        cutoff = time.time() - max_age
        removed = 0
        for key in self._r.keys(_KEY_PREFIX + "*"):
            data = self._r.hgetall(key)
            if not data:
                continue
            updated = float(data.get("updated", 0))
            status = data.get("status", "")
            if updated < cutoff and status in ("done", "error", "cancelled"):
                self._r.delete(key)
                removed += 1
        return removed


class InMemoryQueue(JobQueue):
    """Fallback khi không có Redis — job mất khi restart."""

    def __init__(self):
        self._queue: list[tuple[str, str, dict]] = []
        self._status: dict[str, dict] = {}
        log.info("Using in-memory job queue (Redis not available)")

    def enqueue(self, job_id: str, kind: str, config: dict) -> None:
        self._status[job_id] = {
            "id": job_id,
            "kind": kind,
            "status": "queued",
            "created": time.time(),
            "updated": time.time(),
        }
        self._queue.append((job_id, kind, config))

    def dequeue(self) -> tuple[str, str, dict] | None:
        return self._queue.pop(0) if self._queue else None

    def set_status(self, job_id: str, status: str, **extra) -> None:
        if job_id in self._status:
            self._status[job_id]["status"] = status
            self._status[job_id]["updated"] = time.time()
            self._status[job_id].update(extra)

    def get_status(self, job_id: str) -> dict | None:
        return self._status.get(job_id)

    def list_jobs(self, limit: int = 50) -> list[dict]:
        jobs = sorted(self._status.values(), key=lambda j: j.get("updated", 0), reverse=True)
        return jobs[:limit]

    def cleanup(self, max_age: int = 86400) -> int:
        cutoff = time.time() - max_age
        to_del = [
            jid for jid, info in self._status.items()
            if info.get("updated", 0) < cutoff and info.get("status") in ("done", "error", "cancelled")
        ]
        for jid in to_del:
            del self._status[jid]
        return len(to_del)


_instance: JobQueue | None = None


def get_queue() -> JobQueue:
    """Singleton: trả Redis queue nếu kết nối được, không thì in-memory."""
    global _instance
    if _instance is not None:
        return _instance
    try:
        _instance = RedisQueue()
    except Exception:
        _instance = InMemoryQueue()
    return _instance
