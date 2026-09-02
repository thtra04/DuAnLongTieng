"""Tiện ích ffmpeg / ffprobe / yt-dlp."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Callable

from .config import TOOLS_DIR

_CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0

_TIME_RE = re.compile(r"time=(\d+):(\d{2}):(\d{2})\.(\d{1,2})")
_DUR_RE = re.compile(r"Duration:\s*(\d+):(\d{2}):(\d{2})\.(\d{1,2})")


class MediaError(RuntimeError):
    pass


def _bundled(name: str) -> Path | None:
    exe = name + (".exe" if sys.platform == "win32" else "")
    for base in (TOOLS_DIR / "ffmpeg" / "bin", TOOLS_DIR / "ffmpeg", TOOLS_DIR):
        p = base / exe
        if p.exists():
            return p
    return None


def ffmpeg_exe() -> str:
    p = _bundled("ffmpeg")
    if p:
        return str(p)
    found = shutil.which("ffmpeg")
    if found:
        return found
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as exc:  # pragma: no cover
        raise MediaError(
            "Không tìm thấy ffmpeg. Chạy: uv run python -m app.setup_ffmpeg"
        ) from exc


def ffprobe_exe() -> str | None:
    p = _bundled("ffprobe")
    if p:
        return str(p)
    return shutil.which("ffprobe")


_shim_dir: Path | None = None


def ffmpeg_dir() -> str:
    """Thư mục chứa file tên đúng `ffmpeg(.exe)` — cần cho yt-dlp.

    Bản ffmpeg của gói `imageio-ffmpeg` có tên dạng
    `ffmpeg-win-x86_64-v7.1.exe`; yt-dlp chỉ tìm đúng tên `ffmpeg.exe` nên sẽ
    báo "ffmpeg is not installed". Ở đây ta tạo một bản sao (ưu tiên hardlink)
    tên chuẩn trong tools/ffmpeg/bin/ rồi trỏ yt-dlp vào đó.
    """
    global _shim_dir
    if _shim_dir and (_shim_dir / _exe_name("ffmpeg")).exists():
        return str(_shim_dir)

    real = Path(ffmpeg_exe())
    if real.stem == "ffmpeg":  # đã đúng tên rồi
        _shim_dir = real.parent
        return str(_shim_dir)

    target_dir = TOOLS_DIR / "ffmpeg" / "bin"
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / _exe_name("ffmpeg")
    if not target.exists():
        try:
            os.link(real, target)  # hardlink: không tốn thêm dung lượng
        except Exception:
            shutil.copy2(real, target)
        if sys.platform != "win32":
            target.chmod(0o755)

    probe = ffprobe_exe()
    if probe:
        pt = target_dir / _exe_name("ffprobe")
        if not pt.exists() and Path(probe).parent != target_dir:
            try:
                os.link(probe, pt)
            except Exception:
                try:
                    shutil.copy2(probe, pt)
                except Exception:
                    pass

    _shim_dir = target_dir
    return str(target_dir)


def _exe_name(stem: str) -> str:
    return stem + (".exe" if sys.platform == "win32" else "")


_libass: bool | None = None


def has_libass() -> bool:
    """ffmpeg hiện tại có filter `subtitles` (cần libass) để nung phụ đề không.

    Nhớ kết quả: mỗi lần hỏi là một lần chạy `ffmpeg -filters` (~0,3 giây), mà
    `/api/system` hỏi ngay lúc mở trang. Bản ffmpeg không đổi giữa chừng nên
    hỏi một lần là đủ.
    """
    global _libass
    if _libass is not None:
        return _libass
    _libass = _probe_libass()
    return _libass


def _probe_libass() -> bool:
    try:
        out = subprocess.run(
            [ffmpeg_exe(), "-hide_banner", "-filters"],
            capture_output=True,
            text=True,
            errors="ignore",
            creationflags=_CREATE_NO_WINDOW,
        ).stdout
    except Exception:
        return False
    return bool(re.search(r"^\s*\S*\s+subtitles\s", out, re.M))


def run(cmd: list[str], cwd: str | None = None) -> str:
    proc = subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=True,
        text=True,
        errors="ignore",
        creationflags=_CREATE_NO_WINDOW,
    )
    if proc.returncode != 0:
        tail = "\n".join((proc.stderr or proc.stdout or "").strip().splitlines()[-12:])
        raise MediaError(f"Lệnh thất bại ({proc.returncode}):\n{tail}")
    return proc.stdout


# ------------------------------------------------------------------ probe


def probe(path: str | Path) -> dict:
    """Trả về {duration, width, height, has_audio, fps}."""
    path = str(path)
    probe_bin = ffprobe_exe()
    if probe_bin:
        try:
            out = run(
                [
                    probe_bin, "-v", "error", "-print_format", "json",
                    "-show_format", "-show_streams", path,
                ]
            )
            data = json.loads(out)
            fmt = data.get("format", {})
            info = {
                "duration": float(fmt.get("duration") or 0.0),
                "width": 0, "height": 0, "has_audio": False, "fps": 25.0,
            }
            for st in data.get("streams", []):
                if st.get("codec_type") == "video" and not info["width"]:
                    info["width"] = int(st.get("width") or 0)
                    info["height"] = int(st.get("height") or 0)
                    rate = st.get("avg_frame_rate") or st.get("r_frame_rate") or "25/1"
                    try:
                        num, den = rate.split("/")
                        if float(den):
                            info["fps"] = round(float(num) / float(den), 3)
                    except Exception:
                        pass
                elif st.get("codec_type") == "audio":
                    info["has_audio"] = True
            return info
        except Exception:
            pass

    # Không có ffprobe: parse stderr của ffmpeg
    proc = subprocess.run(
        [ffmpeg_exe(), "-hide_banner", "-i", path],
        capture_output=True, text=True, errors="ignore",
        creationflags=_CREATE_NO_WINDOW,
    )
    err = proc.stderr or ""
    info = {"duration": 0.0, "width": 0, "height": 0, "has_audio": "Audio:" in err, "fps": 25.0}
    m = _DUR_RE.search(err)
    if m:
        h, mm, s, cs = m.groups()
        info["duration"] = int(h) * 3600 + int(mm) * 60 + int(s) + int(cs) / 100
    m = re.search(r"Video:.*?(\d{2,5})x(\d{2,5})", err)
    if m:
        info["width"], info["height"] = int(m.group(1)), int(m.group(2))
    m = re.search(r"(\d+(?:\.\d+)?)\s*fps", err)
    if m:
        info["fps"] = float(m.group(1))
    return info


# ------------------------------------------------------- chạy ffmpeg có tiến độ


def run_ffmpeg_progress(
    args: list[str],
    total_seconds: float,
    on_progress: Callable[[float], None] | None = None,
    cwd: str | None = None,
) -> None:
    cmd = [ffmpeg_exe(), "-hide_banner", "-nostdin", "-y", *args]
    proc = subprocess.Popen(
        cmd,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        errors="ignore",
        bufsize=1,
        creationflags=_CREATE_NO_WINDOW,
    )
    tail: list[str] = []
    assert proc.stdout is not None
    for line in proc.stdout:
        tail.append(line.rstrip())
        if len(tail) > 40:
            tail.pop(0)
        if on_progress and total_seconds > 0:
            m = _TIME_RE.search(line)
            if m:
                h, mm, s, cs = m.groups()
                done = int(h) * 3600 + int(mm) * 60 + int(s) + int(cs) / 100
                on_progress(min(1.0, done / total_seconds))
    proc.wait()
    if proc.returncode != 0:
        raise MediaError("ffmpeg lỗi:\n" + "\n".join(tail[-14:]))
    if on_progress:
        on_progress(1.0)


# ------------------------------------------------------------------ thao tác


def extract_audio(video: str | Path, out_wav: str | Path, on_progress=None) -> Path:
    out_wav = Path(out_wav)
    dur = probe(video).get("duration", 0.0)
    run_ffmpeg_progress(
        ["-i", str(video), "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(out_wav)],
        dur,
        on_progress,
    )
    if not out_wav.exists() or out_wav.stat().st_size < 1024:
        raise MediaError("Không tách được audio — video có thể không có tiếng.")
    return out_wav


def burn_subtitles(
    video: str | Path,
    ass_path: str | Path,
    out_path: str | Path,
    on_progress=None,
    crf: int = 20,
    preset: str = "medium",
) -> Path:
    """Nung (hardsub) file .ass vào video.

    Chạy ffmpeg với cwd = thư mục chứa .ass và dùng tên file tương đối để né
    hoàn toàn chuyện escape đường dẫn Windows trong filter `subtitles`.
    """
    ass_path = Path(ass_path)
    out_path = Path(out_path)
    workdir = ass_path.parent
    dur = probe(video).get("duration", 0.0)
    vf = f"subtitles={ass_path.name}"
    run_ffmpeg_progress(
        [
            "-i", str(Path(video).resolve()),
            "-vf", vf,
            "-c:v", "libx264", "-preset", preset, "-crf", str(crf),
            "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k",
            "-movflags", "+faststart",
            str(out_path.resolve()),
        ],
        dur,
        on_progress,
        cwd=str(workdir),
    )
    return out_path


def mux_soft_subs(
    video: str | Path,
    srt_path: str | Path,
    out_path: str | Path,
    lang: str = "und",
    on_progress=None,
) -> Path:
    """Gắn phụ đề dạng track (bật/tắt được) — nhanh vì không encode lại."""
    out_path = Path(out_path)
    dur = probe(video).get("duration", 0.0)
    codec = "mov_text" if out_path.suffix.lower() in (".mp4", ".m4v", ".mov") else "srt"
    run_ffmpeg_progress(
        [
            "-i", str(Path(video).resolve()),
            "-i", str(Path(srt_path).resolve()),
            "-map", "0", "-map", "1",
            "-c", "copy", "-c:s", codec,
            "-metadata:s:s:0", f"language={lang}",
            "-disposition:s:0", "default",
            str(out_path.resolve()),
        ],
        dur,
        on_progress,
    )
    return out_path


# ------------------------------------------------------------------ yt-dlp

_BVID_RE = re.compile(r"/video/(BV[0-9A-Za-z]+)", re.I)


def _ytdlp_message(exc: Exception) -> str:
    """Gọt bớt phần lằng nhằng trong thông báo lỗi của yt-dlp."""
    msg = str(exc).strip()
    msg = re.sub(r"^ERROR:\s*", "", msg)
    msg = re.sub(r"\s*;\s*please report this issue.*$", "", msg, flags=re.S)
    msg = re.sub(r"\s*Confirm you are on the latest version.*$", "", msg, flags=re.S)
    return msg or "yt-dlp không đọc được link này."


def list_parts(url: str, limit: int = 500) -> dict:
    """Xem link có nhiều phần hay không (playlist YouTube, anthology bilibili…).

    Chưa tải gì cả — chỉ đọc danh sách để hỏi người dùng muốn xử lý phần nào.

    Trả về::

        {"multi": True, "title": "...", "count": 5, "truncated": False,
         "parts": [{"index": 1, "title": "P-1", "duration": 2898.0}, ...]}
    """
    import yt_dlp

    opts = {
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "noplaylist": False,          # phải cho phép playlist mới thấy các phần
        "extract_flat": "in_playlist",  # không giải từng phần -> nhanh
        "skip_download": True,
        "retries": 3,
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except yt_dlp.utils.YoutubeDLError as exc:
        raise MediaError(_ytdlp_message(exc)) from exc

    if not info:
        raise MediaError("Không đọc được thông tin từ link này.")

    entries = info.get("entries")
    if entries is None:  # link trỏ tới đúng một video
        return {
            "multi": False,
            "title": info.get("title") or "",
            "count": 1,
            "truncated": False,
            "duration": float(info.get("duration") or 0.0),
            "parts": [],
        }

    entries = [e for e in list(entries) if e]
    total = info.get("playlist_count") or len(entries)
    parts: list[dict] = []
    for i, e in enumerate(entries[:limit], 1):
        parts.append(
            {
                "index": int(e.get("playlist_index") or i),
                "title": (e.get("title") or "").strip(),
                "duration": float(e.get("duration") or 0.0),
            }
        )

    # bilibili: extract_flat chỉ trả về URL, phải lấy thêm tên & thời lượng
    if any(not p["title"] or not p["duration"] for p in parts):
        try:
            _fill_bilibili_parts(url, parts)
        except Exception:
            pass  # chỉ là thông tin cho đẹp — thiếu thì vẫn còn số thứ tự phần

    return {
        "multi": len(entries) > 1,
        "title": info.get("title") or "",
        "count": int(total),
        "truncated": len(entries) > len(parts),
        "duration": 0.0,
        "parts": parts,
    }


def _fill_bilibili_parts(url: str, parts: list[dict]) -> None:
    """Điền tên & thời lượng từng phần cho link bilibili (1 request cho mọi phần)."""
    m = _BVID_RE.search(url)
    if not m:
        return

    import urllib.request

    api = f"https://api.bilibili.com/x/player/pagelist?bvid={m.group(1)}&jsonp=jsonp"
    req = urllib.request.Request(
        api,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            "Referer": "https://www.bilibili.com/",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8", "replace"))
    except Exception:
        return  # không lấy được thì thôi, vẫn còn số thứ tự phần
    if data.get("code") != 0:
        return

    pages = {int(p.get("page") or 0): p for p in (data.get("data") or [])}
    for part in parts:
        page = pages.get(part["index"])
        if not page:
            continue
        if not part["title"]:
            part["title"] = (page.get("part") or "").strip()
        if not part["duration"]:
            part["duration"] = float(page.get("duration") or 0.0)


def download_url(
    url: str,
    outdir: str | Path,
    on_progress=None,
    on_log=None,
    part: int | None = None,
) -> Path:
    """Tải video từ YouTube/TikTok/bilibili… bằng yt-dlp.

    `part` là số thứ tự phần (1-based) khi link có nhiều phần — xem `list_parts`.
    Không truyền thì lấy đúng một video (phần đầu), không đụng tới playlist.
    """
    import yt_dlp

    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    result: dict = {}
    part = int(part) if part else None

    def hook(d: dict) -> None:
        if d.get("status") == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            done = d.get("downloaded_bytes") or 0
            if on_progress and total:
                on_progress(min(0.99, done / total))
        elif d.get("status") == "finished":
            if on_progress:
                on_progress(1.0)

    prefix = f"p{part}." if part else ""
    opts = {
        "outtmpl": str(outdir / f"{prefix}%(title).80B.%(ext)s"),
        "format": "bv*[height<=1080]+ba/b[height<=1080]/bv*+ba/b",
        "merge_output_format": "mp4",
        "noplaylist": part is None,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "progress_hooks": [hook],
        "ffmpeg_location": ffmpeg_dir(),
        "restrictfilenames": True,
        "windowsfilenames": True,
        "concurrent_fragment_downloads": 4,
        "retries": 5,
    }
    if part:
        opts["playlist_items"] = str(part)

    with yt_dlp.YoutubeDL(opts) as ydl:
        try:
            info = ydl.extract_info(url, download=True)
        except yt_dlp.utils.YoutubeDLError as exc:
            raise MediaError(_ytdlp_message(exc)) from exc
        if not info:
            raise MediaError("yt-dlp không trả về thông tin video.")
        if info.get("entries") is not None:  # chọn 1 phần -> yt-dlp gói trong playlist
            picked = [e for e in list(info["entries"]) if e]
            if not picked:
                raise MediaError(
                    f"Không tải được phần {part} — link có thể không có phần này."
                )
            info = picked[0]
        result["title"] = info.get("title") or "video"
        path = Path(ydl.prepare_filename(info))

    if not path.exists():
        for cand in (path.with_suffix(".mp4"), path.with_suffix(".mkv"), path.with_suffix(".webm")):
            if cand.exists():
                path = cand
                break
    if not path.exists():
        files = sorted(outdir.glob("*"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not files:
            raise MediaError("yt-dlp không tải được file nào.")
        path = files[0]

    if on_log:
        on_log(f"Đã tải: {path.name}")
    return path
