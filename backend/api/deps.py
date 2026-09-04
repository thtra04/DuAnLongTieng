"""Tiện ích dùng chung cho các router: kiểm tra id, phục vụ file có Range, tìm lại video."""

from __future__ import annotations

from pathlib import Path

from fastapi import HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse

from ..config import JOB_DIR, UPLOAD_DIR
from ..core import media

VIDEO_EXT = {
    ".mp4", ".mkv", ".mov", ".avi", ".webm", ".flv", ".m4v", ".ts", ".wmv",
    ".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg",
}


def safe_id(value: str | None) -> str:
    """Chỉ lấy phần tên cuối của một id, bỏ mọi thành phần đường dẫn.

    `media_id` và `job_id` được ghép thẳng vào đường dẫn thư mục. Không lọc thì
    `"../../.."` trỏ ra ngoài `data/`, và `/api/analyze` sẽ nhận file đầu tiên
    tìm được ở đó rồi đem đi nhận dạng — đọc trộm file bất kỳ trên máy chủ. Ca
    này có thật, đã dựng lại được bằng test.

    Trả về "" cho id rỗng hoặc chỉ gồm dấu chấm, để bên gọi báo lỗi bình thường.
    """
    name = Path(str(value or "")).name.strip()
    return "" if name in ("", ".", "..") else name


def ranged_file(path: Path, request: Request, mime: str):
    """Phục vụ file có hỗ trợ HTTP Range để tua video trong trình duyệt."""
    file_size = path.stat().st_size
    range_header = request.headers.get("range")
    if not range_header:
        return FileResponse(path, media_type=mime, headers={"Accept-Ranges": "bytes"})

    try:
        units, _, rng = range_header.partition("=")
        start_s, _, end_s = rng.partition("-")
        start = int(start_s) if start_s else 0
        end = int(end_s) if end_s else file_size - 1
    except ValueError:
        raise HTTPException(416, "Range không hợp lệ")
    end = min(end, file_size - 1)
    if start > end:
        raise HTTPException(416, "Range không hợp lệ")
    length = end - start + 1

    def iterator():
        with path.open("rb") as fh:
            fh.seek(start)
            remaining = length
            while remaining > 0:
                chunk = fh.read(min(1024 * 512, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
                yield chunk

    return StreamingResponse(
        iterator(),
        status_code=206,
        media_type=mime,
        headers={
            "Content-Range": f"bytes {start}-{end}/{file_size}",
            "Accept-Ranges": "bytes",
            "Content-Length": str(length),
        },
    )


def find_source_video(job_id: str, media_id: str | None) -> Path | None:
    """Tìm lại file video gốc: thư mục job trước, rồi tới thư mục upload."""
    job_id = safe_id(job_id)
    media_id = safe_id(media_id)
    if not job_id:
        return None
    for folder in (JOB_DIR / job_id / "source", JOB_DIR / job_id):
        if folder.is_dir():
            for p in sorted(folder.glob("*")):
                if p.is_file() and p.suffix.lower() in VIDEO_EXT:
                    return p
    if media_id:
        folder = UPLOAD_DIR / media_id
        if folder.is_dir():
            files = [p for p in folder.glob("*") if p.is_file()]
            if files:
                return files[0]
    return None


def needs_video(cfg: dict) -> bool:
    """Định dạng đang chọn có cần tới file video gốc không.

    SRT/VTT/TXT/ASS chỉ là chữ nên xuất được kể cả khi video đã bị dọn; chỉ nung
    phụ đề, gắn track và lồng tiếng mới thật sự cần video.
    """
    outputs = cfg.get("outputs") or {}
    return bool(outputs.get("burn") or outputs.get("soft") or outputs.get("dub"))


def rebuild_state(job_id: str, cfg: dict) -> dict:
    """Dựng lại state.json từ dữ liệu trình duyệt gửi lên.

    Cần khi thư mục job đã bị xoá hoặc server khởi động lại — người dùng vẫn giữ
    nguyên phụ đề đã biên tập trên màn hình nên không việc gì phải làm lại từ đầu.
    """
    video = find_source_video(job_id, cfg.get("media_id"))
    if not video:
        if needs_video(cfg):
            raise HTTPException(
                410,
                "Không tìm thấy file video gốc trên máy chủ (có thể đã bị dọn dẹp). "
                "Hãy quay lại bước 1 và chọn lại video — phần phụ đề bạn đã sửa vẫn được giữ.",
            )
        # Chỉ xuất file chữ: không cần video, cũng không cần biết khung hình
        return {
            "video_path": "",
            "video_name": cfg.get("video_name") or "phu-de",
            "info": {},
            "source_lang": cfg.get("source_lang") or None,
            "target_lang": cfg.get("target_lang") or "",
            "cues": cfg.get("cues") or [],
            "cfg": {},
        }
    try:
        info = media.probe(video)
    except Exception as exc:
        raise HTTPException(400, f"Không đọc được video gốc: {exc}") from exc

    return {
        "video_path": str(video),
        "video_name": video.name,
        "info": info,
        "source_lang": cfg.get("source_lang") or None,
        "target_lang": cfg.get("target_lang") or "",
        "cues": cfg.get("cues") or [],
        "cfg": {},
    }
