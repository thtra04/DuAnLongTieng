"""Tải bản ffmpeg đầy đủ (kèm ffprobe + libass) về thư mục tools/.

Chạy:  uv run python -m app.setup_ffmpeg

Bản ffmpeg đi kèm gói `imageio-ffmpeg` thường đã đủ để nung phụ đề, nhưng
thiếu `ffprobe`. Script này tải bản essentials của gyan.dev (Windows) hoặc
bản static của johnvansickle (Linux) để có đầy đủ công cụ.
"""

from __future__ import annotations

import shutil
import sys
import tarfile
import tempfile
import urllib.request
import zipfile
from pathlib import Path

from .config import TOOLS_DIR

WIN_URL = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
LINUX_URL = "https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz"


def _report(done: int, block: int, total: int) -> None:
    if total <= 0:
        return
    pct = min(100, done * block * 100 // total)
    mb = total / 1024 / 1024
    print(f"\r  Đang tải… {pct:3d}%  ({mb:.0f} MB)", end="", flush=True)


def main() -> int:
    dest = TOOLS_DIR / "ffmpeg"
    exe = dest / "bin" / ("ffmpeg.exe" if sys.platform == "win32" else "ffmpeg")
    if exe.exists():
        print(f"✓ Đã có ffmpeg tại: {exe}")
        return 0

    url = WIN_URL if sys.platform == "win32" else LINUX_URL
    print("Tải ffmpeg đầy đủ (kèm ffprobe, libass)")
    print(f"  Nguồn: {url}")
    print("  Dung lượng khoảng 80–150 MB.\n")

    TOOLS_DIR.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        archive = tmpdir / ("ffmpeg.zip" if sys.platform == "win32" else "ffmpeg.tar.xz")
        try:
            urllib.request.urlretrieve(url, archive, _report)
        except Exception as exc:
            print(f"\n✕ Tải thất bại: {exc}")
            print("  Cách khác: tải thủ công rồi giải nén vào thư mục tools/ffmpeg/")
            return 1
        print("\n  Đang giải nén…")

        extract_to = tmpdir / "x"
        if archive.suffix == ".zip":
            with zipfile.ZipFile(archive) as zf:
                zf.extractall(extract_to)
        else:
            with tarfile.open(archive) as tf:
                tf.extractall(extract_to)

        # tìm thư mục chứa binary
        found = None
        for cand in extract_to.rglob("ffmpeg*"):
            if cand.is_file() and cand.stem == "ffmpeg":
                found = cand.parent
                break
        if not found:
            print("✕ Không tìm thấy ffmpeg trong gói tải về.")
            return 1

        bin_dir = dest / "bin"
        bin_dir.mkdir(parents=True, exist_ok=True)
        for name in ("ffmpeg", "ffprobe", "ffplay"):
            for src in found.glob(name + "*"):
                if src.is_file():
                    shutil.copy2(src, bin_dir / src.name)

    if exe.exists():
        if sys.platform != "win32":
            for f in (dest / "bin").iterdir():
                f.chmod(0o755)
        print(f"\n✓ Xong! ffmpeg đã sẵn sàng tại: {dest / 'bin'}")
        return 0

    print("\n✕ Cài đặt không thành công.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
