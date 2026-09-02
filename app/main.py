"""FastAPI server cho VSub Studio."""

from __future__ import annotations

import json
import mimetypes
import os
import re
import shutil
import threading
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import diarize, dubbing, films, media, pipeline, projects, series, translate
from .config import (
    AI_MODELS,
    ASR_MODELS,
    DATA_DIR,
    DEFAULT_ASR_MODEL,
    JOB_DIR,
    MAX_UPLOAD_BYTES,
    UPLOAD_DIR,
    WEB_DIR,
)
from .jobs import create_job, get_job, run_in_thread
from .languages import LANGUAGES
from .subtitles import DEFAULT_STYLE

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


VIDEO_EXT = {
    ".mp4", ".mkv", ".mov", ".avi", ".webm", ".flv", ".m4v", ".ts", ".wmv",
    ".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg",
}

@asynccontextmanager
async def _lifespan(_app: FastAPI):
    """Nạp trước những thứ nặng mà `/api/system` cần, ngay khi server chạy.

    `asr.gpu_available()` phải `import ctranslate2` thật mới hỏi được số GPU —
    mất ~3,4 giây. Không nạp trước thì cái giá đó rơi đúng vào lần mở trang đầu
    tiên của người dùng. Hâm nóng ở đây thì lúc trình duyệt tải xong HTML/CSS/JS
    rồi mới gọi `/api/system`, thư viện đã nằm sẵn trong bộ nhớ.

    Chạy trong thread nền và nuốt mọi lỗi: đây chỉ là hâm nóng, hỏng thì
    `/api/system` tự nạp lại như cũ — không được phép làm server không lên.
    """
    def warm() -> None:
        try:
            from . import asr

            asr.gpu_available()
            media.has_libass()
        except Exception:
            pass

    threading.Thread(target=warm, daemon=True, name="warmup").start()
    yield


app = FastAPI(title="VSub Studio", docs_url=None, redoc_url=None, lifespan=_lifespan)

if (WEB_DIR / "assets").is_dir():
    app.mount("/assets", StaticFiles(directory=WEB_DIR / "assets"), name="assets")


# ------------------------------------------------------------------ trang

# no-cache: luôn hỏi lại server, tránh chuyện sửa code mà trình duyệt vẫn
# chạy bản cũ trong cache (chỉ tốn 1 request 304 nếu file không đổi).
_NO_CACHE = {"Cache-Control": "no-cache"}


@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    html = (WEB_DIR / "index.html").read_text(encoding="utf-8")
    # Gắn thời điểm sửa file vào /app.js và /style.css: sửa code là URL đổi theo,
    # trình duyệt buộc phải tải bản mới thay vì dùng bản cũ trong cache.
    for name in ("app.js", "style.css"):
        try:
            stamp = int((WEB_DIR / name).stat().st_mtime)
        except OSError:
            continue
        html = html.replace(f'"/{name}"', f'"/{name}?v={stamp}"')
    return HTMLResponse(html, headers=_NO_CACHE)


@app.get("/app.js")
def app_js() -> FileResponse:
    return FileResponse(
        WEB_DIR / "app.js", media_type="application/javascript", headers=_NO_CACHE
    )


@app.get("/style.css")
def app_css() -> FileResponse:
    return FileResponse(WEB_DIR / "style.css", media_type="text/css", headers=_NO_CACHE)


# ------------------------------------------------------------------ hệ thống


@app.get("/api/system")
def system_info() -> dict:
    from . import asr

    ff_ok, ff_path, ff_err = True, "", ""
    try:
        ff_path = media.ffmpeg_exe()
    except Exception as exc:
        ff_ok, ff_err = False, str(exc)

    engines = []
    for e in translate.ENGINES:
        ok, why = translate.engine_available(e["id"])
        engines.append({**e, "available": ok, "reason": why})

    tts_ok, tts_reason = dubbing.available()
    dia_ok, dia_reason = diarize.available()

    return {
        "diarize": {
            "available": dia_ok,
            "reason": dia_reason,
            # Có token sẵn trong biến môi trường thì giao diện khỏi hỏi lại
            "has_token": bool(diarize.hf_token()),
            "model": diarize.MODEL_ID,
        },
        "ffmpeg": {
            "ok": ff_ok,
            "path": ff_path,
            "error": ff_err,
            "libass": media.has_libass() if ff_ok else False,
            "ffprobe": bool(media.ffprobe_exe()),
        },
        "tts": {
            "available": tts_ok,
            "reason": tts_reason,
            "styles": dubbing.STYLES,
            "clone_id": dubbing.CLONE_VOICE,
        },
        "gpu": asr.gpu_available(),
        "languages": LANGUAGES,
        "asr_models": ASR_MODELS,
        "default_asr_model": DEFAULT_ASR_MODEL,
        "engines": engines,
        "ai_models": AI_MODELS,
        "default_style": DEFAULT_STYLE,
        "has_anthropic_key": bool(os.environ.get("ANTHROPIC_API_KEY")),
        "has_openai_key": bool(os.environ.get("OPENAI_API_KEY")),
        "max_upload_mb": MAX_UPLOAD_BYTES // (1024 * 1024),
    }


@app.get("/api/translation-cache")
def translation_cache_info() -> dict:
    return translate.cache_info()


@app.delete("/api/translation-cache")
def translation_cache_clear() -> dict:
    return {"deleted": translate.clear_cache()}


# --------------------------------------------------------------- lồng tiếng


@app.get("/api/tts/voices")
def tts_voices() -> dict:
    """Danh sách giọng đọc. Lần gọi đầu có thể mất ~1 phút vì phải tải model.

    Trả về luôn `clone` (nhân bản giọng dùng được hay chưa) để giao diện khoá
    sẵn mục đó — thà báo trước còn hơn để người dùng chờ hết job xuất mới lỗi.
    Chỗ này mới kiểm tra torch, không kiểm ở `/api/system`, vì `import torch`
    mất vài giây và sẽ làm chậm lúc mở trang.
    """
    # deep=True: chỗ này vốn đã phải chờ nạp model nên kiểm kỹ được, và lỗi kiểu
    # thiếu DLL onnxruntime sẽ hiện đúng tên thay vì báo chung chung "chưa cài".
    ok, reason = dubbing.available(deep=True)
    if not ok:
        return {"available": False, "reason": reason, "voices": [], "styles": dubbing.STYLES}
    try:
        voices = dubbing.list_voices()
    except Exception as exc:
        return {"available": False, "reason": str(exc), "voices": [], "styles": dubbing.STYLES}
    clone_ok, clone_reason = dubbing.clone_available()
    return {
        "available": True,
        "reason": "",
        "voices": voices,
        "styles": dubbing.STYLES,
        "clone_id": dubbing.CLONE_VOICE,
        "clone": clone_ok,
        "clone_reason": clone_reason,
    }


@app.post("/api/tts/preview")
def tts_preview(payload: dict):
    ok, reason = dubbing.available()
    if not ok:
        raise HTTPException(400, reason)
    text = (payload.get("text") or "").strip()
    voice = payload.get("voice") or ""
    if voice == dubbing.CLONE_VOICE:
        raise HTTPException(
            400, "Giọng nhân bản chỉ tạo được lúc xuất video (cần cắt mẫu từ chính video)."
        )
    out = DATA_DIR / "preview"
    out.mkdir(parents=True, exist_ok=True)
    path = out / "last.wav"
    try:
        dubbing.preview(text, voice=voice, style=payload.get("style") or "tu_nhien", out_path=path)
    except Exception as exc:
        raise HTTPException(500, f"Không đọc thử được: {exc}") from exc
    return FileResponse(path, media_type="audio/wav", headers={"Cache-Control": "no-store"})


# --------------------------------------------------------------- link video


@app.post("/api/link/inspect")
def link_inspect(payload: dict) -> dict:
    """Xem link có nhiều phần không, để hỏi người dùng chọn phần nào.

    Bilibili (và playlist YouTube) hay gộp nhiều tập trong một link — mỗi tập
    có thể dài mấy tiếng, nên phải hỏi trước khi tải.
    """
    url = ((payload or {}).get("url") or "").strip()
    if not url:
        raise HTTPException(400, "Thiếu link video.")
    if not re.match(r"^https?://", url, re.I):
        raise HTTPException(400, "Link phải bắt đầu bằng http:// hoặc https://")
    try:
        return media.list_parts(url)
    except media.MediaError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(400, f"Không đọc được link: {exc}") from exc


# ------------------------------------------------------------------ upload


@app.post("/api/upload")
async def upload(file: UploadFile = File(...)) -> dict:
    ext = Path(file.filename or "video.mp4").suffix.lower() or ".mp4"
    if ext not in {
        ".mp4", ".mkv", ".mov", ".avi", ".webm", ".flv", ".m4v", ".ts", ".wmv",
        ".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg",
    }:
        raise HTTPException(400, f"Định dạng không hỗ trợ: {ext}")

    media_id = uuid.uuid4().hex[:12]
    target_dir = UPLOAD_DIR / media_id
    target_dir.mkdir(parents=True, exist_ok=True)
    dest = target_dir / (pipeline.safe_stem(file.filename or "video") + ext)

    size = 0
    with dest.open("wb") as fh:
        while chunk := await file.read(1024 * 1024):
            size += len(chunk)
            if size > MAX_UPLOAD_BYTES:
                fh.close()
                shutil.rmtree(target_dir, ignore_errors=True)
                raise HTTPException(413, "File quá lớn.")
            fh.write(chunk)

    try:
        info = media.probe(dest)
    except Exception as exc:
        shutil.rmtree(target_dir, ignore_errors=True)
        raise HTTPException(400, f"Không đọc được video: {exc}") from exc

    # `probe` trả về số 0 chứ không ném lỗi khi file không phải media, nên một
    # file rác vẫn qua được tới tận bước nghe rồi mới hỏng. Chặn ngay ở đây.
    if not info.get("duration") and not info.get("width") and not info.get("has_audio"):
        shutil.rmtree(target_dir, ignore_errors=True)
        raise HTTPException(
            400,
            "File này không phải video hay âm thanh đọc được. "
            "Kiểm tra lại file, hoặc thử đổi sang .mp4 rồi tải lên lại.",
        )

    return {
        "media_id": media_id,
        "name": dest.name,
        "size": size,
        "path": str(dest),
        "info": info,
    }


@app.get("/api/media/{media_id}/stream")
def stream_media(media_id: str, request: Request):
    media_id = safe_id(media_id)
    if not media_id:
        raise HTTPException(404, "Không tìm thấy media.")
    folder = UPLOAD_DIR / media_id
    if not folder.is_dir():
        # cũng cho phép xem video đã tải từ URL trong job
        folder = JOB_DIR / media_id / "source"
    files = [p for p in folder.glob("*") if p.is_file()] if folder.is_dir() else []
    if not files:
        raise HTTPException(404, "Không tìm thấy media.")
    path = files[0]
    mime = mimetypes.guess_type(path.name)[0] or "video/mp4"
    return _ranged_file(path, request, mime)


def _ranged_file(path: Path, request: Request, mime: str):
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

    from fastapi.responses import StreamingResponse

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


# ------------------------------------------------------------------ job


@app.post("/api/analyze")
async def analyze(payload: dict) -> dict:
    cfg = dict(payload or {})
    source_type = cfg.get("source_type", "file")

    if source_type == "file":
        media_id = safe_id(cfg.get("media_id"))
        cfg["media_id"] = media_id
        folder = UPLOAD_DIR / media_id if media_id else None
        files = [p for p in folder.glob("*") if p.is_file()] if folder and folder.is_dir() else []
        if not files:
            raise HTTPException(400, "Chưa chọn video (media_id không hợp lệ).")
        cfg["video_path"] = str(files[0])
    elif source_type == "url":
        if not (cfg.get("url") or "").strip():
            raise HTTPException(400, "Thiếu link video.")
        raw_part = cfg.get("part")
        if raw_part in (None, "", 0):
            cfg["part"] = None
        else:
            try:
                cfg["part"] = max(1, int(raw_part))
            except (TypeError, ValueError):
                raise HTTPException(400, "Số phần cần tải không hợp lệ.") from None
        # Tên bộ & tổng số tập do trình duyệt gửi kèm — chỉ để gom nhóm về sau,
        # nên cứ cắt gọn thay vì báo lỗi nếu gửi sai kiểu.
        cfg["series_name"] = str(cfg.get("series_name") or "").strip()[:160]
        try:
            cfg["series_total"] = max(0, int(cfg.get("series_total") or 0))
        except (TypeError, ValueError):
            cfg["series_total"] = 0
    else:
        raise HTTPException(400, "Nguồn video không hợp lệ.")

    mode = cfg.get("sub_mode", "auto")
    if mode == "text" and not (cfg.get("script_text") or "").strip():
        raise HTTPException(400, "Chưa dán văn bản kịch bản.")
    if mode == "srt" and not (cfg.get("subtitle_text") or "").strip():
        raise HTTPException(400, "Chưa nạp file phụ đề .srt/.vtt.")
    if cfg.get("translate") and not cfg.get("target_lang"):
        raise HTTPException(400, "Chưa chọn ngôn ngữ đích.")

    if cfg.get("translate"):
        ok, why = translate.engine_available(cfg.get("engine", "google"))
        if not ok:
            raise HTTPException(400, why)

    # Kiểm tra nhận diện người nói TRƯỚC khi chạy: bước này nằm sau khâu nghe
    # lời thoại, để lỗi ở đó thì người dùng đã chờ mất cả chục phút.
    if cfg.get("diarize"):
        ok, why = diarize.available(cfg.get("hf_token", ""))
        if not ok:
            raise HTTPException(400, why)
        for key in ("num_speakers", "max_speakers"):
            raw = cfg.get(key)
            if raw in (None, "", 0):
                cfg[key] = None
                continue
            try:
                cfg[key] = max(1, min(20, int(raw)))
            except (TypeError, ValueError):
                raise HTTPException(400, f"Số nhân vật không hợp lệ ({key}).") from None

    # Đang làm cho một tập cụ thể của một bộ phim? Kiểm tra trước khi chạy, để
    # không phải nghe cả video xong mới phát hiện bộ/tập không tồn tại.
    film_id = (cfg.get("film_id") or "").strip()
    episode_no = None
    if film_id:
        try:
            episode_no = int(cfg.get("episode_no"))
        except (TypeError, ValueError):
            raise HTTPException(400, "Thiếu số tập cần làm.") from None
        target_film = next((f for f in films.all_films() if f["id"] == film_id), None)
        if not target_film:
            raise HTTPException(404, "Bộ phim này không còn nữa.")
        if episode_no not in {int(e.get("no") or 0) for e in target_film.get("episodes") or []}:
            raise HTTPException(404, f"Bộ phim này không có tập {episode_no}.")

    job = create_job("analyze", pipeline.analyze_steps(cfg))
    job.log("Bắt đầu xử lý.")

    def target(j):
        pipeline.run_analyze(j, cfg)
        if film_id and episode_no is not None:
            try:
                films.bind(film_id, episode_no, j.id)
                j.log(f"Đã gắn kết quả vào tập {episode_no}.")
            except films.FilmError as exc:
                # Phụ đề vẫn xong, chỉ là không gắn được vào bộ -> nói rõ,
                # đừng làm cả job thành lỗi.
                j.log(f"Không gắn được vào tập {episode_no}: {exc}")

    run_in_thread(job, target)
    return {"job_id": job.id}


def _find_source_video(job_id: str, media_id: str | None) -> Path | None:
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


def _needs_video(cfg: dict) -> bool:
    """Định dạng đang chọn có cần tới file video gốc không.

    SRT/VTT/TXT/ASS chỉ là chữ nên xuất được kể cả khi video đã bị dọn; chỉ nung
    phụ đề, gắn track và lồng tiếng mới thật sự cần video.
    """
    outputs = cfg.get("outputs") or {}
    return bool(outputs.get("burn") or outputs.get("soft") or outputs.get("dub"))


def _rebuild_state(job_id: str, cfg: dict) -> dict:
    """Dựng lại state.json từ dữ liệu trình duyệt gửi lên.

    Cần khi thư mục job đã bị xoá hoặc server khởi động lại — người dùng vẫn giữ
    nguyên phụ đề đã biên tập trên màn hình nên không việc gì phải làm lại từ đầu.
    """
    video = _find_source_video(job_id, cfg.get("media_id"))
    if not video:
        if _needs_video(cfg):
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


@app.post("/api/jobs/{job_id}/render")
async def render(job_id: str, payload: dict) -> dict:
    cfg = dict(payload or {})
    state_path = JOB_DIR / job_id / "state.json"

    if state_path.exists():
        state = json.loads(state_path.read_text(encoding="utf-8"))
        # File video có thể đã bị xoá dù state.json còn.
        # Phải kiểm chuỗi rỗng riêng: Path("") ra "." mà "." thì luôn tồn tại.
        saved = state.get("video_path") or ""
        if not (saved and Path(saved).is_file()):
            found = _find_source_video(job_id, cfg.get("media_id"))
            if found:
                state["video_path"] = str(found)
            elif _needs_video(cfg):
                raise HTTPException(
                    410,
                    "File video gốc không còn trên máy chủ nên không nung / gắn track / "
                    "lồng tiếng được. Bỏ chọn các mục đó thì vẫn xuất được SRT · VTT · TXT, "
                    "hoặc quay lại bước 1 chọn lại video.",
                )
            else:
                state["video_path"] = ""  # chỉ xuất file chữ, không cần video
    else:
        if not cfg.get("cues"):
            raise HTTPException(
                410,
                "Phiên làm việc đã hết hạn trên máy chủ. Hãy chạy lại từ bước 1.",
            )
        state = _rebuild_state(job_id, cfg)

    # Cho phép người dùng sửa phụ đề trước khi xuất
    if cfg.get("cues"):
        state["cues"] = cfg["cues"]
    if cfg.get("source_lang") and not state.get("source_lang"):
        state["source_lang"] = cfg["source_lang"]
    if cfg.get("target_lang") and not state.get("target_lang"):
        state["target_lang"] = cfg["target_lang"]

    state_path.parent.mkdir(parents=True, exist_ok=True)
    pipeline.write_utf8(state_path, json.dumps(state, ensure_ascii=False, indent=1))

    if not state.get("cues"):
        raise HTTPException(400, "Không có dòng phụ đề nào để xuất.")
    if not any(cfg.get("outputs", {}).values()):
        raise HTTPException(400, "Chưa chọn định dạng nào để xuất.")

    job = create_job("render", pipeline.render_steps(cfg))
    job.result = {"source_job": job_id}
    job.log("Bắt đầu xuất file.")
    # File xuất ra nằm ở thư mục của job render này, không nằm cùng job phân
    # tích. Ghi lại mối liên hệ để mục "Dự án đã làm" còn tìm thấy chúng sau
    # khi khởi động lại tool (danh sách job trong RAM thì mất).
    pipeline.write_utf8(
        job.dir / "render.json",
        json.dumps({"source_job": job_id}, ensure_ascii=False),
    )

    def target(j):
        j.result = {}
        pipeline.run_render(j, state, cfg)

    # ghi output vào thư mục của job render
    run_in_thread(job, target)
    return {"job_id": job.id}


# ------------------------------------------------------------------ dự án


@app.get("/api/projects")
def projects_list() -> dict:
    items = projects.list_all()
    return {
        "projects": items,
        "total_size": sum(it["size"] for it in items),
    }


# ------------------------------------------------------------- bộ phim & tập


@app.get("/api/films")
def films_list() -> dict:
    """Nội dung dashboard: các bộ phim kèm tập, và job chưa thuộc bộ nào."""
    return projects.dashboard()


@app.post("/api/films")
def film_create(payload: dict) -> dict:
    """Tạo bộ phim.

    Có `url` thì đọc luôn link để tạo sẵn từng tập, và tự gắn những tập đã làm
    trước đó (job cũ cùng link, cùng số phần) vào đúng chỗ.
    """
    data = payload or {}
    parts: list[dict] = []
    url = (data.get("url") or "").strip()

    if url:
        try:
            info = media.list_parts(url)
        except media.MediaError as exc:
            raise HTTPException(400, str(exc)) from exc
        parts = info.get("parts") or []
        if not parts:  # link một video -> bộ một tập
            parts = [{"index": 1, "title": info.get("title") or "", "duration": info.get("duration") or 0}]
        if not (data.get("name") or "").strip():
            data["name"] = info.get("title") or url

    try:
        film = films.create(data.get("name") or "", url=url, parts=parts)
    except films.FilmError as exc:
        raise HTTPException(400, str(exc)) from exc

    adopted = _adopt_existing(film) if url else 0
    return {"film": film, "adopted": adopted}


def _adopt_existing(film: dict) -> int:
    """Gắn các job cũ cùng link vào tập tương ứng của bộ mới tạo.

    Chỉ chạy đúng một lần lúc tạo bộ, và chỉ nhận job chưa thuộc bộ nào — cố ý
    không đoán ngầm về sau, để dashboard chỉ có một quy tắc: bộ do bạn tạo.
    """
    key = series.key_for(film.get("url") or "")
    if not key:
        return 0
    bound = films.bound_jobs()
    numbers = {int(e.get("no") or 0) for e in film.get("episodes") or []}

    count = 0
    for item in projects.list_all(limit=10_000):
        if item["id"] in bound or item["series_key"] != key:
            continue
        part = item["part"] or 1
        if part not in numbers:
            continue
        try:
            films.bind(film["id"], part, item["id"])
            count += 1
        except films.FilmError:
            continue
    return count


@app.patch("/api/films/{film_id}")
def film_rename(film_id: str, payload: dict) -> dict:
    try:
        film = films.rename(film_id, (payload or {}).get("name") or "")
    except films.FilmError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"ok": True, "film": film}


@app.delete("/api/films/{film_id}")
def film_delete(film_id: str, with_jobs: int = 1, with_source: int = 1) -> dict:
    """Xoá bộ. `with_jobs=1` (mặc định) xoá luôn phụ đề & file của mọi tập."""
    try:
        film = films.remove(film_id)
    except films.FilmError as exc:
        raise HTTPException(404, str(exc)) from exc

    freed, removed = 0, 0
    if with_jobs:
        for episode in film.get("episodes") or []:
            job_id = episode.get("job")
            if not job_id:
                continue
            result = projects.delete(job_id, with_source=bool(with_source))
            if result["ok"]:
                removed += 1
                freed += result["freed"]
    return {"ok": True, "removed": removed, "freed": freed}


@app.post("/api/films/{film_id}/episodes")
def episode_add(film_id: str, payload: dict) -> dict:
    data = payload or {}
    raw_no = data.get("no")
    try:
        no = int(raw_no) if raw_no not in (None, "") else None
    except (TypeError, ValueError):
        raise HTTPException(400, "Số tập không hợp lệ.") from None
    try:
        episode = films.add_episode(film_id, no=no, title=data.get("title") or "")
    except films.FilmError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"ok": True, "episode": episode}


@app.delete("/api/films/{film_id}/episodes/{no}")
def episode_remove(film_id: str, no: int, with_job: int = 1, with_source: int = 1) -> dict:
    try:
        episode = films.remove_episode(film_id, no)
    except films.FilmError as exc:
        raise HTTPException(404, str(exc)) from exc
    if not episode:
        raise HTTPException(404, f"Bộ này không có tập {no}.")

    freed = 0
    job_id = episode.get("job")
    if with_job and job_id:
        result = projects.delete(job_id, with_source=bool(with_source))
        freed = result["freed"]
    return {"ok": True, "freed": freed}


@app.post("/api/films/{film_id}/episodes/{no}/bind")
def episode_bind(film_id: str, no: int, payload: dict) -> dict:
    """Gắn một job đã làm sẵn vào tập — dùng cho mục 'chưa thuộc bộ nào'."""
    job_id = ((payload or {}).get("job") or "").strip()
    if not job_id:
        raise HTTPException(400, "Thiếu id dự án cần gắn.")
    if not projects.summary(Path(job_id).name):
        raise HTTPException(404, "Không tìm thấy dự án cần gắn.")
    try:
        episode = films.bind(film_id, no, Path(job_id).name)
    except films.FilmError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"ok": True, "episode": episode}


@app.get("/api/projects/{job_id}")
def project_get(job_id: str) -> dict:
    item = projects.full(Path(job_id).name)
    if not item:
        raise HTTPException(404, "Không tìm thấy dự án này (có thể đã bị xoá).")
    return item


@app.get("/api/projects/{job_id}/video")
def project_video(job_id: str, request: Request):
    path = projects.video_path(Path(job_id).name)
    if not path:
        raise HTTPException(
            404,
            "Video gốc của dự án không còn trên máy. Phụ đề vẫn xem và xuất được, "
            "nhưng không xem trước trên video và không nung được.",
        )
    mime = mimetypes.guess_type(path.name)[0] or "video/mp4"
    return _ranged_file(path, request, mime)


@app.get("/api/projects/{job_id}/files/{name}")
def project_file(job_id: str, name: str):
    path = projects.output_file(Path(job_id).name, name)
    if not path:
        raise HTTPException(404, "File không tồn tại.")
    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return FileResponse(path, media_type=mime, filename=path.name)


@app.delete("/api/projects/{job_id}")
def project_delete(job_id: str, with_source: int = 0) -> dict:
    result = projects.delete(Path(job_id).name, with_source=bool(with_source))
    if not result["ok"]:
        raise HTTPException(404, "Không tìm thấy dự án này.")
    return result


# ------------------------------------------------------------------ job


@app.get("/api/jobs/{job_id}")
def job_status(job_id: str) -> dict:
    job = get_job(job_id)
    if not job:
        raise HTTPException(404, "Job không tồn tại.")
    return job.to_dict()


@app.post("/api/jobs/{job_id}/cancel")
def job_cancel(job_id: str) -> dict:
    job = get_job(job_id)
    if not job:
        raise HTTPException(404, "Job không tồn tại.")
    job.cancel.set()
    job.log("Nhận lệnh huỷ…")
    return {"ok": True}


@app.get("/api/jobs/{job_id}/files/{name}")
def job_file(job_id: str, name: str, download: int = 1):
    job = get_job(job_id)
    if not job:
        raise HTTPException(404, "Job không tồn tại.")
    safe = Path(name).name
    path = job.dir / safe
    if not path.exists() or not path.is_file():
        raise HTTPException(404, "File không tồn tại.")
    mime = mimetypes.guess_type(safe)[0] or "application/octet-stream"
    return FileResponse(
        path,
        media_type=mime,
        filename=safe if download else None,
    )


@app.exception_handler(HTTPException)
async def http_error(request: Request, exc: HTTPException):
    return JSONResponse({"error": exc.detail}, status_code=exc.status_code)
