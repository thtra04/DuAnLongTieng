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
