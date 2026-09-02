"""Kiểm thử máy trạng thái job và tiến độ theo bước."""

from __future__ import annotations

import threading
import time

import pytest

from app.jobs import Job, JobCancelled, Step, create_job, get_job, run_in_thread


def steps():
    return [Step("a", "Bước A", weight=1.0), Step("b", "Bước B", weight=3.0)]


def wait_done(job: Job, timeout: float = 10.0) -> None:
    end = time.time() + timeout
    while time.time() < end:
        if job.status in ("done", "error", "cancelled"):
            return
        time.sleep(0.01)
    raise AssertionError(f"job không kết thúc, đang ở trạng thái {job.status}")


# ---------------------------------------------------------- tiến độ


def test_job_moi_chua_co_tien_do():
    job = Job(id="x", kind="analyze", steps=steps())
    assert job.overall == 0.0


def test_tien_do_tinh_theo_trong_so():
    """Bước B nặng gấp 3 bước A, xong B phải nhảy 75% chứ không phải 50%."""
    job = Job(id="x", kind="analyze", steps=steps())
    job.finish_step("b")
    assert job.overall == pytest.approx(0.75)


def test_bo_qua_buoc_van_tinh_la_xong():
    job = Job(id="x", kind="analyze", steps=steps())
    job.skip_step("a", "không cần")
    assert job.overall == pytest.approx(0.25)
    assert job.step("a").status == "skipped"


def test_tien_do_giua_chung_duoc_tinh():
    job = Job(id="x", kind="analyze", steps=steps())
    job.set_step_progress("b", 0.5)
    assert job.overall == pytest.approx(0.375)


def test_tien_do_bi_kep_trong_khoang_0_1():
    job = Job(id="x", kind="analyze", steps=steps())
    job.set_step_progress("a", 5.0)
    assert job.step("a").progress == 1.0
    job.set_step_progress("a", -3.0)
    assert job.step("a").progress == 0.0


def test_xong_het_la_mot_tram_phan_tram():
    job = Job(id="x", kind="analyze", steps=steps())
    job.finish_step("a")
    job.finish_step("b")
    assert job.overall == 1.0


def test_khong_co_buoc_nao_khong_gay_chia_cho_khong():
    assert Job(id="x", kind="analyze", steps=[]).overall == 0.0


def test_thao_tac_len_buoc_khong_ton_tai_khong_gay_loi():
    job = Job(id="x", kind="analyze", steps=steps())
    job.start_step("khong-co")
    job.finish_step("khong-co")
    job.set_step_progress("khong-co", 0.5)
    assert job.overall == 0.0


# ------------------------------------------------------------- log


def test_log_co_dau_thoi_gian():
    job = Job(id="x", kind="analyze", steps=[])
    job.log("thử")
    assert job.logs[0].endswith("thử")
    assert job.logs[0].startswith("[")


def test_log_bi_cat_bot_khi_qua_dai():
    """Job chạy 9 tiếng sinh rất nhiều dòng log — không được phình vô hạn."""
    job = Job(id="x", kind="analyze", steps=[])
    for i in range(600):
        job.log(f"dòng {i}")
    assert len(job.logs) <= 400
    assert "dòng 599" in job.logs[-1], "phải giữ log mới nhất, không phải log cũ nhất"


def test_to_dict_chi_tra_log_gan_day():
    job = Job(id="x", kind="analyze", steps=[])
    for i in range(300):
        job.log(f"dòng {i}")
    assert len(job.to_dict()["logs"]) <= 120


def test_to_dict_bo_duoc_log():
    job = Job(id="x", kind="analyze", steps=steps())
    assert "logs" not in job.to_dict(include_logs=False)


def test_to_dict_du_khoa_giao_dien_can():
    job = Job(id="x", kind="analyze", steps=steps())
    data = job.to_dict()
    assert set(data) >= {"id", "kind", "status", "progress", "steps", "error", "result"}


# ------------------------------------------------------------ huỷ


def test_check_cancel_nem_loi_khi_da_huy():
    job = Job(id="x", kind="analyze", steps=[])
    job.check_cancel()  # chưa huỷ thì im lặng
    job.cancel.set()
    with pytest.raises(JobCancelled):
        job.check_cancel()


def test_huy_giua_chung_cho_trang_thai_cancelled():
    job = create_job("analyze", steps())
    started = threading.Event()

    def target(j):
        started.set()
        for _ in range(500):
            j.check_cancel()
            time.sleep(0.01)

    run_in_thread(job, target)
    started.wait(5)
    job.cancel.set()
    wait_done(job)
    assert job.status == "cancelled"


# --------------------------------------------------------- chạy nền


def test_chay_xong_thi_status_la_done():
    job = create_job("analyze", steps())
    run_in_thread(job, lambda j: j.finish_step("a"))
    wait_done(job)
    assert job.status == "done"


def test_loi_duoc_ghi_lai_kem_traceback():
    job = create_job("analyze", steps())

    def no(j):
        raise ValueError("hỏng rồi")

    run_in_thread(job, no)
    wait_done(job)
    assert job.status == "error"
    assert "hỏng rồi" in job.error
    assert any("LỖI" in ln for ln in job.logs)


def test_buoc_dang_chay_bi_danh_dau_loi():
    job = create_job("analyze", steps())

    def no(j):
        j.start_step("a")
        raise RuntimeError("đứt")

    run_in_thread(job, no)
    wait_done(job)
    assert job.step("a").status == "error"


def test_loi_khong_co_thong_diep_van_co_ten_loai():
    job = create_job("analyze", steps())
    run_in_thread(job, lambda j: (_ for _ in ()).throw(KeyError()))
    wait_done(job)
    assert job.error


# ------------------------------------------------------------- kho job


def test_tao_job_lay_lai_duoc_theo_id():
    job = create_job("analyze", steps())
    assert get_job(job.id) is job


def test_id_khong_trung_nhau():
    ids = {create_job("analyze", []).id for _ in range(50)}
    assert len(ids) == 50


def test_job_khong_ton_tai_tra_none():
    assert get_job("khong-co-that") is None


def test_thu_muc_job_duoc_tao():
    job = create_job("analyze", [])
    assert job.dir.is_dir()
