"""Sửa cache HuggingFace bị mất symlink.

Trong cache HuggingFace, file nằm trong `snapshots/<rev>/` chỉ là **symlink** trỏ
tới dữ liệu thật ở `blobs/`. Copy hay giải nén thư mục cache trên Windows (hoặc
clone bằng git không bật `core.symlinks`) làm symlink bị "dẹp" thành file text
vài chục byte, nội dung đúng bằng cái đường dẫn đó::

    data/models/models--Systran--faster-whisper-medium/
      blobs/9b45e1009dcc…            1457 MB   <- model thật, vẫn còn nguyên
      snapshots/08e178…/model.bin      76 byte <- chỉ là chữ "../../blobs/9b45e…"

Model không mất, nhưng thư viện đọc file text kia rồi báo lỗi rất khó hiểu —
CTranslate2 đọc 4 byte đầu (`../..`) thành số phiên bản:

    Unsupported model binary version … the model has binary version v774843950

`repair()` tìm đúng những file như vậy và dựng lại bằng hardlink: không tốn thêm
dung lượng, và không cần quyền admin như tạo symlink trên Windows.
"""

from __future__ import annotations

import os
import re
import shutil
from pathlib import Path

# Nội dung của một symlink bị dẹp — chỉ vậy, không gì khác.
_STUB_RE = re.compile(rb"^(?:\.\.[\\/])+blobs[\\/]([0-9a-f]{32,64})$")
# Symlink dẹp chỉ dài vài chục byte; file to hơn ngần này chắc chắn là file thật.
_MAX_STUB_BYTES = 300


def repair(root: str | Path) -> list[str]:
    """Dựng lại các file snapshot bị mất symlink trong cache `root`.

    Chạy lại nhiều lần vô hại. Trả về danh sách file đã sửa (đường dẫn tương đối).
    """
    root = Path(root)
    fixed: list[str] = []

    for snapshots in root.glob("models--*/snapshots"):
        blobs = snapshots.parent / "blobs"
        if not blobs.is_dir():
            continue

        for path in snapshots.rglob("*"):
            blob = _stub_target(path, blobs)
            if blob is None:
                continue
            # link vào tên tạm rồi thay thế -> không có lúc nào file bị thiếu
            tmp = path.with_name(path.name + ".vsub-relink")
            try:
                tmp.unlink(missing_ok=True)
                try:
                    os.link(blob, tmp)
                except OSError:
                    shutil.copy2(blob, tmp)  # khác ổ đĩa/không hardlink được
                os.replace(tmp, path)
            except OSError:
                tmp.unlink(missing_ok=True)
                continue
            fixed.append(str(path.relative_to(root)))

    return fixed


def _stub_target(path: Path, blobs: Path) -> Path | None:
    """Trả về blob mà `path` đang trỏ tới, nếu nó là symlink bị dẹp."""
    try:
        if path.is_symlink() or not path.is_file():
            return None
        if path.stat().st_size > _MAX_STUB_BYTES:
            return None
        match = _STUB_RE.match(path.read_bytes().strip())
    except OSError:
        return None
    if not match:
        return None
    blob = blobs / match.group(1).decode()
    return blob if blob.is_file() else None
