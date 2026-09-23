"""Kiểm thử sửa cache HuggingFace bị mất symlink.

Copy thư mục cache trên Windows làm symlink trong `snapshots/` bị dẹp thành file
text vài chục byte chứa đúng đường dẫn tới blob. Model vẫn còn nguyên nhưng thư
viện đọc file text đó rồi báo lỗi rất khó hiểu (CTranslate2 đọc 4 byte đầu
`../..` thành số phiên bản: "binary version v774843950").
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from backend.core.hf_cache import repair

BLOB = "9b45e1009dcc4ab601eff815b61d80e60ce3fd8c74c1a14f4a282258286b51ae"
NOI_DUNG = b"day-la-model-that" * 100


def dung_cache(root, *, stub: bytes | None = None, ten="model.bin"):
    """Dựng một cây cache HuggingFace giả. `stub` là nội dung file trong snapshots."""
    model = root / "models--Systran--faster-whisper-medium"
    blobs = model / "blobs"
    snap = model / "snapshots" / "abc123"
    blobs.mkdir(parents=True)
    snap.mkdir(parents=True)

    (blobs / BLOB).write_bytes(NOI_DUNG)
    if stub is not None:
        (snap / ten).write_bytes(stub)
    return snap / ten


def test_dung_lai_file_bi_dep(workdir):
    path = dung_cache(workdir, stub=f"../../blobs/{BLOB}".encode())
    da_sua = repair(workdir)

    assert len(da_sua) == 1
    assert path.read_bytes() == NOI_DUNG, "phải trỏ được về dữ liệu thật trong blobs"


def test_chap_nhan_dau_gach_nguoc_kieu_windows(workdir):
    path = dung_cache(workdir, stub=f"..\\..\\blobs\\{BLOB}".encode())
    repair(workdir)
    assert path.read_bytes() == NOI_DUNG


def test_khong_dung_toi_file_that(workdir):
    """File model thật (to) không được coi là symlink bị dẹp."""
    path = dung_cache(workdir, stub=b"x" * 5000)
    assert repair(workdir) == []
    assert path.read_bytes() == b"x" * 5000


def test_khong_dung_toi_file_text_binh_thuong(workdir):
    path = dung_cache(workdir, stub=b'{"config": true}', ten="config.json")
    assert repair(workdir) == []
    assert path.read_bytes() == b'{"config": true}'


def test_blob_khong_ton_tai_thi_bo_qua(workdir):
    thieu = "f" * 64
    path = dung_cache(workdir, stub=f"../../blobs/{thieu}".encode())
    assert repair(workdir) == []
    assert path.exists(), "không được xoá file khi chưa có gì thay thế"


def test_chay_lai_nhieu_lan_vo_hai(workdir):
    dung_cache(workdir, stub=f"../../blobs/{BLOB}".encode())
    assert len(repair(workdir)) == 1
    assert repair(workdir) == [], "lần hai không còn gì để sửa"


def test_khong_co_thu_muc_blobs(workdir):
    model = workdir / "models--x--y"
    (model / "snapshots" / "rev").mkdir(parents=True)
    (model / "snapshots" / "rev" / "model.bin").write_bytes(f"../../blobs/{BLOB}".encode())
    assert repair(workdir) == []


def test_cache_rong(workdir):
    assert repair(workdir) == []


def test_khong_de_lai_file_tam(workdir):
    dung_cache(workdir, stub=f"../../blobs/{BLOB}".encode())
    repair(workdir)
    assert not list(workdir.rglob("*.vsub-relink"))


def test_sua_nhieu_file_cung_luc(workdir):
    snap = dung_cache(workdir, stub=f"../../blobs/{BLOB}".encode())
    for ten in ("tokenizer.json", "vocabulary.txt"):
        (snap.parent / ten).write_bytes(f"../../blobs/{BLOB}".encode())

    assert len(repair(workdir)) == 3


# ------------------------------------------------------------ dereference


def _make_symlink(link, target):
    try:
        os.symlink(target, link)
    except (OSError, NotImplementedError):
        pytest.skip("máy này không tạo được symlink (Windows cần Developer Mode)")


def test_dereference_thay_symlink_bang_hardlink(tmp_path):
    from backend.core import hf_cache

    repo = tmp_path / "models--pnnbao-ump--VieNeu-TTS-v3-Turbo"
    blobs = repo / "blobs"
    snap = repo / "snapshots" / "abc" / "onnx_int8"
    blobs.mkdir(parents=True)
    snap.mkdir(parents=True)
    (blobs / "b1").write_bytes(b"graph")
    (blobs / "b2").write_bytes(b"external data")
    _make_symlink(snap / "model.onnx", blobs / "b1")
    _make_symlink(snap / "model.data", blobs / "b2")
    assert (snap / "model.data").is_symlink()

    changed = hf_cache.dereference(tmp_path)

    assert sorted(changed) == [
        str(Path("models--pnnbao-ump--VieNeu-TTS-v3-Turbo/snapshots/abc/onnx_int8/model.data")),
        str(Path("models--pnnbao-ump--VieNeu-TTS-v3-Turbo/snapshots/abc/onnx_int8/model.onnx")),
    ]
    # Không còn symlink, nội dung giữ nguyên, và resolve() nằm đúng trong snapshot
    for name, content in (("model.onnx", b"graph"), ("model.data", b"external data")):
        p = snap / name
        assert not p.is_symlink()
        assert p.read_bytes() == content
        assert p.resolve().parent == snap.resolve()
    # Chạy lại vô hại
    assert hf_cache.dereference(tmp_path) == []


def test_dereference_chi_dung_repo_duoc_chon(tmp_path):
    from backend.core import hf_cache

    for repo_name in ("models--a--x", "models--b--y"):
        blobs = tmp_path / repo_name / "blobs"
        snap = tmp_path / repo_name / "snapshots" / "r"
        blobs.mkdir(parents=True)
        snap.mkdir(parents=True)
        (blobs / "b").write_bytes(b"x")
        _make_symlink(snap / "f.onnx", blobs / "b")

    changed = hf_cache.dereference(tmp_path, repos=("models--a--x",))

    assert changed == [str(Path("models--a--x/snapshots/r/f.onnx"))]
    assert (tmp_path / "models--b--y/snapshots/r/f.onnx").is_symlink()


def test_dereference_thu_muc_khong_ton_tai(tmp_path):
    from backend.core import hf_cache

    assert hf_cache.dereference(tmp_path / "khong-co") == []
