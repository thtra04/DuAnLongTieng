"""Tạo biểu tượng vsub.ico và gói payload.zip cho bộ cài (build_exe.ps1 gọi).

    python make_payload.py icon <file.ico>
    python make_payload.py payload <payload.zip> <VSubStudio.exe> <uv.exe>

Gói gồm mọi tệp git đang theo dõi hoặc chưa theo dõi nhưng không bị .gitignore loại (tức là đúng mã
nguồn, không kèm data/, .venv/, mô hình), cộng VSubStudio.exe ở gốc và tools/uv.exe.
"""
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKIP_PREFIX = ("installer/windows/dist/", "dist/", ".claude/")


def icon(out: Path) -> None:
    from PIL import Image, ImageDraw

    s = 1024
    im = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    k = s / 108
    d.rounded_rectangle((6 * k, 6 * k, 102 * k, 102 * k), radius=18 * k, fill=(0x1C, 0x19, 0x17, 255))
    d.polygon([(38 * k, 34 * k), (38 * k, 74 * k), (68 * k, 54 * k)], fill=(0xFA, 0xF8, 0xF3, 255))
    w = int(5 * k)
    gold = (0xE2, 0xB6, 0x59, 255)
    d.arc((58 * k, 38 * k, 90 * k, 70 * k), start=-48, end=48, fill=gold, width=w)
    d.arc((54 * k, 26 * k, 110 * k, 82 * k), start=-46, end=46, fill=gold, width=w)
    im.save(out, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print("icon", out)


def payload(out: Path, launcher: Path, uv: Path) -> None:
    names = subprocess.run(["git", "-c", "core.quotepath=off", "ls-files", "-co", "--exclude-standard", "-z"],
                           cwd=ROOT, capture_output=True, check=True).stdout.decode("utf-8").split("\0")
    files = [n for n in names if n and not n.startswith(SKIP_PREFIX) and (ROOT / n).is_file()]
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for n in sorted(files):
            z.write(ROOT / n, n)
        z.write(launcher, "VSubStudio.exe")
        z.write(uv, "tools/uv.exe")
    print("payload", out, len(files) + 2, "tệp", round(out.stat().st_size / 2**20, 1), "MB")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    if sys.argv[1] == "icon":
        icon(Path(sys.argv[2]))
    else:
        payload(Path(sys.argv[2]), Path(sys.argv[3]), Path(sys.argv[4]))
