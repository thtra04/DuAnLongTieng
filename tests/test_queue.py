"""Kiểm thử hàng đợi tác vụ (HP-7): in-memory, Redis (giả lập) và fallback."""

from __future__ import annotations

import json
import time

import pytest

from backend.core import jobs, queue


@pytest.fixture(autouse=True)
def _reset_singleton(monkeypatch):
    monkeypatch.setattr(queue, "_instance", None)


# ------------------------------------------------------------ in-memory


def test_inmemory_enqueue_dequeue_fifo():
    q = queue.InMemoryQueue()
    q.enqueue("a", "analyze", {"x": 1})
    q.enqueue("b", "render", {"y": 2})
    assert q.dequeue() == ("a", "analyze", {"x": 1})
    assert q.dequeue() == ("b", "render", {"y": 2})
    assert q.dequeue() is None


def test_inmemory_status():
    q = queue.InMemoryQueue()
    q.enqueue("a", "analyze", {})
    assert q.get_status("a")["status"] == "queued"
    q.set_status("a", "error", error="hỏng")
    info = q.get_status("a")
    assert info["status"] == "error" and info["error"] == "hỏng"
    assert q.get_status("khong-co") is None


def test_inmemory_set_status_job_la_khong_no():
    q = queue.InMemoryQueue()
    q.set_status("la", "done")
    assert q.get_status("la") is None


def test_inmemory_list_moi_nhat_truoc():
    q = queue.InMemoryQueue()
    q.enqueue("a", "analyze", {})
    q.enqueue("b", "analyze", {})
    q.set_status("a", "running")  # a được cập nhật sau -> lên đầu
    ids = [j["id"] for j in q.list_jobs()]
    assert ids == ["a", "b"]
    assert len(q.list_jobs(limit=1)) == 1


def test_inmemory_cleanup_chi_xoa_job_cu_da_xong():
    q = queue.InMemoryQueue()
    for jid, status in (("done-cu", "done"), ("run-cu", "running"), ("done-moi", "done")):
        q.enqueue(jid, "analyze", {})
        q.set_status(jid, status)
    q._status["done-cu"]["updated"] = time.time() - 10_000
    q._status["run-cu"]["updated"] = time.time() - 10_000

    assert q.cleanup(max_age=3600) == 1
    assert set(q._status) == {"run-cu", "done-moi"}


# ------------------------------------------------------------ redis (giả lập)


class FakeRedis:
    """Đủ dùng cho RedisQueue: hset/hgetall/lpush/rpop/keys/delete/ping."""

    def __init__(self, fail_ping: bool = False):
        self.h: dict[str, dict] = {}
        self.lists: dict[str, list] = {}
        self.fail_ping = fail_ping

    def ping(self):
        if self.fail_ping:
            raise ConnectionError("no redis")
        return True

    def hset(self, key, mapping):
        self.h.setdefault(key, {}).update({k: str(v) for k, v in mapping.items()})

    def hgetall(self, key):
        return dict(self.h.get(key, {}))

    def lpush(self, key, value):
        self.lists.setdefault(key, []).insert(0, value)

    def rpop(self, key):
        lst = self.lists.get(key) or []
        return lst.pop() if lst else None

    def keys(self, pattern):
        prefix = pattern.rstrip("*")
        return [k for k in self.h if k.startswith(prefix)]

    def delete(self, key):
        self.h.pop(key, None)


@pytest.fixture
def fake_redis(monkeypatch):
    fake = FakeRedis()
    import types

    mod = types.SimpleNamespace(from_url=lambda url, decode_responses=True: fake)
    monkeypatch.setitem(__import__("sys").modules, "redis", mod)
    return fake


def test_redis_enqueue_dequeue_fifo(fake_redis):
    q = queue.RedisQueue("redis://x")
    q.enqueue("a", "analyze", {"lang": "vi"})
    q.enqueue("b", "render", {})
    assert q.dequeue() == ("a", "analyze", {"lang": "vi"})
    assert q.dequeue() == ("b", "render", {})
    assert q.dequeue() is None


def test_redis_dequeue_job_mat_hash_tra_none(fake_redis):
    q = queue.RedisQueue("redis://x")
    q.enqueue("a", "analyze", {})
    fake_redis.h.clear()
    assert q.dequeue() is None


def test_redis_status_serialize_dict_list(fake_redis):
    q = queue.RedisQueue("redis://x")
    q.enqueue("a", "analyze", {})
    q.set_status("a", "done", result={"cues": 3}, tags=["x"], error="")
    info = q.get_status("a")
    assert info["status"] == "done"
    assert json.loads(info["result"]) == {"cues": 3}
    assert json.loads(info["tags"]) == ["x"]
    assert info["error"] == ""
    assert q.get_status("khong-co") is None


def test_redis_list_va_cleanup(fake_redis):
    q = queue.RedisQueue("redis://x")
    q.enqueue("cu", "analyze", {})
    q.enqueue("moi", "analyze", {})
    q.set_status("cu", "done")
    q.set_status("moi", "done")
    fake_redis.h[queue._KEY_PREFIX + "cu"]["updated"] = str(time.time() - 10_000)

    assert [j["id"] for j in q.list_jobs()] == ["moi", "cu"]
    assert q.cleanup(max_age=3600) == 1
    assert [j["id"] for j in q.list_jobs()] == ["moi"]


# ------------------------------------------------------------ get_queue fallback


def test_get_queue_dung_redis_khi_ket_noi_duoc(fake_redis):
    assert isinstance(queue.get_queue(), queue.RedisQueue)
    assert queue.get_queue() is queue.get_queue(), "singleton"


def test_get_queue_fallback_inmemory_khi_khong_co_redis(monkeypatch):
    import types

    mod = types.SimpleNamespace(from_url=lambda *a, **k: FakeRedis(fail_ping=True))
    monkeypatch.setitem(__import__("sys").modules, "redis", mod)
    assert isinstance(queue.get_queue(), queue.InMemoryQueue)


def test_get_queue_fallback_khi_chua_cai_redis(monkeypatch):
    monkeypatch.setitem(__import__("sys").modules, "redis", None)
    assert isinstance(queue.get_queue(), queue.InMemoryQueue)


# ------------------------------------------------------------ nối với jobs.py


def test_create_job_day_vao_hang_doi(fake_redis):
    job = jobs.create_job("analyze", [jobs.Step("a", "A")], config={"src": "vi"})
    info = queue.get_queue().get_status(job.id)
    assert info["status"] == "queued"
    assert json.loads(info["config"]) == {"src": "vi"}


def test_run_in_thread_dong_bo_trang_thai_done(fake_redis):
    job = jobs.create_job("analyze", [jobs.Step("a", "A")])
    jobs.run_in_thread(job, lambda j: j.finish_step("a"))
    for _ in range(200):
        if job.status == "done":
            break
        time.sleep(0.01)
    assert job.status == "done"
    assert queue.get_queue().get_status(job.id)["status"] == "done"


def test_run_in_thread_dong_bo_trang_thai_error(fake_redis):
    def hong(j):
        raise ValueError("nổ")

    job = jobs.create_job("analyze", [jobs.Step("a", "A")])
    jobs.run_in_thread(job, hong)
    for _ in range(200):
        if job.status == "error":
            break
        time.sleep(0.01)
    info = queue.get_queue().get_status(job.id)
    assert info["status"] == "error" and info["error"] == "nổ"


def test_jobs_van_chay_khi_queue_hong(monkeypatch):
    """Queue lỗi không được làm job manager gục — chỉ mất phần lưu trạng thái."""

    class Nổ:
        def enqueue(self, *a, **k):
            raise RuntimeError("redis chết")

        def set_status(self, *a, **k):
            raise RuntimeError("redis chết")

    monkeypatch.setattr(queue, "_instance", Nổ())
    job = jobs.create_job("analyze", [jobs.Step("a", "A")])
    jobs.run_in_thread(job, lambda j: None)
    for _ in range(200):
        if job.status == "done":
            break
        time.sleep(0.01)
    assert job.status == "done"
