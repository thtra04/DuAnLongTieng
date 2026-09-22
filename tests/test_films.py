"""Kiểm thử kho bộ phim & tập — SQLite qua SQLAlchemy.

Luồng đúng thứ tự: tạo bộ -> tạo tập -> gắn video vào tập. Một tập tồn tại
TRƯỚC khi có video, nên `job` của nó ban đầu là None.
"""

from __future__ import annotations

import pytest

from backend.store import films
from backend.store.films import FilmError


@pytest.fixture(autouse=True)
def kho_tam(tmp_db):
    """Mỗi test một DB riêng — không đụng dữ liệu thật của người dùng."""


# ------------------------------------------------------------ tạo bộ


def test_tao_bo_va_doc_lai():
    film = films.create("Đại Hán Thiên Mệnh")
    assert film["name"] == "Đại Hán Thiên Mệnh"
    assert film["episodes"] == []
    assert films.all_films()[0]["id"] == film["id"]


def test_ten_bo_khong_duoc_rong():
    with pytest.raises(FilmError):
        films.create("   ")


def test_ten_bo_bi_gon_khoang_trang():
    assert films.create("  Tên   có   nhiều   dấu cách  ")["name"] == "Tên có nhiều dấu cách"


def test_ten_bo_bi_cat_khi_qua_dai():
    assert len(films.create("x" * 500)["name"]) <= films.MAX_NAME


def test_tao_bo_kem_danh_sach_phan_thi_co_san_tap():
    parts = [
        {"index": 1, "title": "Tập một", "duration": 2400},
        {"index": 2, "title": "Tập hai", "duration": 2500},
    ]
    film = films.create("Bộ có link", url="https://x/y", parts=parts)
    assert [e["no"] for e in film["episodes"]] == [1, 2]
    assert film["episodes"][0]["title"] == "Tập một"
    assert film["episodes"][0]["job"] is None, "tập mới tạo thì chưa có video"


def test_khong_vuot_qua_so_tap_toi_da():
    parts = [{"index": i, "title": "", "duration": 0} for i in range(1, 700)]
    film = films.create("Bộ dài", parts=parts)
    assert len(film["episodes"]) <= films.MAX_EPISODES


def test_moi_tao_nam_tren_dau():
    films.create("Cũ")
    moi = films.create("Mới")
    assert films.all_films()[0]["id"] == moi["id"]


# --------------------------------------------------------- sửa & xoá


def test_doi_ten_bo():
    film = films.create("Tên cũ")
    assert films.rename(film["id"], "Tên mới")["name"] == "Tên mới"
    assert films.all_films()[0]["name"] == "Tên mới"


def test_doi_ten_bo_khong_ton_tai():
    with pytest.raises(FilmError):
        films.rename("khong-co", "Tên")


def test_xoa_bo():
    film = films.create("Sắp xoá")
    films.remove(film["id"])
    assert films.all_films() == []


def test_xoa_bo_khong_ton_tai():
    with pytest.raises(FilmError):
        films.remove("khong-co")


def test_dat_lai_link():
    film = films.create("Bộ")
    assert films.set_url(film["id"], "https://moi")["url"] == "https://moi"


# ------------------------------------------------------------- tập


def test_them_tap_tu_dong_danh_so_tiep():
    film = films.create("Bộ")
    assert films.add_episode(film["id"])["no"] == 1
    assert films.add_episode(film["id"])["no"] == 2


def test_them_tap_theo_so_chi_dinh():
    film = films.create("Bộ")
    assert films.add_episode(film["id"], no=7)["no"] == 7
    assert films.add_episode(film["id"])["no"] == 8, "số kế tiếp tính từ số lớn nhất"


def test_khong_them_trung_so_tap():
    film = films.create("Bộ")
    films.add_episode(film["id"], no=3)
    with pytest.raises(FilmError):
        films.add_episode(film["id"], no=3)


def test_so_tap_phai_tu_mot_tro_len():
    film = films.create("Bộ")
    with pytest.raises(FilmError):
        films.add_episode(film["id"], no=0)


def test_tap_luon_sap_theo_so():
    film = films.create("Bộ")
    for n in (5, 1, 3):
        films.add_episode(film["id"], no=n)
    assert [e["no"] for e in films.all_films()[0]["episodes"]] == [1, 3, 5]


def test_xoa_tap_tra_ve_tap_da_xoa():
    film = films.create("Bộ")
    films.add_episode(film["id"], no=1)
    assert films.remove_episode(film["id"], 1)["no"] == 1
    assert films.all_films()[0]["episodes"] == []


def test_xoa_tap_khong_ton_tai_tra_none():
    film = films.create("Bộ")
    assert films.remove_episode(film["id"], 99) is None


# --------------------------------------------------------- gắn job


def test_gan_job_vao_tap():
    film = films.create("Bộ")
    films.add_episode(film["id"], no=1)
    assert films.bind(film["id"], 1, "job-abc")["job"] == "job-abc"
    assert films.bound_jobs()["job-abc"] == (film["id"], 1)


def test_mot_job_chi_thuoc_mot_tap():
    """Gắn lại sang tập khác thì tập cũ phải nhả ra, không hiện ở hai nơi."""
    film = films.create("Bộ")
    films.add_episode(film["id"], no=1)
    films.add_episode(film["id"], no=2)
    films.bind(film["id"], 1, "job-abc")
    films.bind(film["id"], 2, "job-abc")

    eps = {e["no"]: e["job"] for e in films.all_films()[0]["episodes"]}
    assert eps == {1: None, 2: "job-abc"}


def test_job_khong_dinh_o_hai_bo_khac_nhau():
    a = films.create("Bộ A")
    b = films.create("Bộ B")
    films.add_episode(a["id"], no=1)
    films.add_episode(b["id"], no=1)
    films.bind(a["id"], 1, "job-x")
    films.bind(b["id"], 1, "job-x")

    assert len(films.bound_jobs()) == 1


def test_gan_vao_tap_khong_ton_tai():
    film = films.create("Bộ")
    with pytest.raises(FilmError):
        films.bind(film["id"], 99, "job-abc")


def test_xoa_job_thi_tap_quay_ve_chua_co_video():
    film = films.create("Bộ")
    films.add_episode(film["id"], no=1)
    films.bind(film["id"], 1, "job-abc")

    assert films.unbind_job("job-abc") is True
    assert films.all_films()[0]["episodes"][0]["job"] is None
    assert films.bound_jobs() == {}


def test_go_job_khong_gan_o_dau_thi_khong_doi_gi():
    assert films.unbind_job("job-la") is False


# ------------------------------------------------------- DB rỗng


def test_db_rong_thi_kho_rong():
    assert films.all_films() == []
