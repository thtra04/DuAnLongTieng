"""Điểm vào của backend: dựng ứng dụng FastAPI, ghép các router, phục vụ giao diện.

Ranh giới frontend / backend:

* Backend chỉ nói chuyện qua HTTP JSON dưới `/api/...` — mọi router nằm ở
  `backend/api/`, lõi xử lý ở `backend/core/`, lưu trữ ở `backend/store/`.
  Tài liệu API tự sinh ở `/api/docs`.
* Frontend (`frontend/`) là HTML/CSS/JS tĩnh, gọi backend qua `API_BASE`
  (mặc định rỗng = cùng origin). Backend phục vụ nó cho tiện, nhưng frontend
  chạy được bằng bất kỳ máy chủ tĩnh nào khi đặt `VSUB_CORS_ORIGINS`.
"""

from __future__ import annotations

import os
import re
import threading
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.datastructures import MutableHeaders

from . import __version__
from .api import access, ai, auth, collaboration, films, jobs, media, projects, system, tts
from .api.deps import safe_id
from .config import FRONTEND_DIR
from .core import media as core_media
from .db import init_db
from .store.projects import ScriptChanged


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    """Khởi tạo DB và hâm nóng những thứ nặng khi server chạy."""
    init_db()

    def warm() -> None:
        try:
            from .core import asr

            asr.gpu_available()
            core_media.has_libass()
        except Exception:
            pass

    threading.Thread(target=warm, daemon=True, name="warmup").start()
    yield


app = FastAPI(
    title="VSub Studio",
    version=__version__,
    docs_url="/api/docs",
    redoc_url=None,
    openapi_url="/api/openapi.json",
    lifespan=_lifespan,
)


class _PrivateApiResponses:
    """Don't cache private scripts/media past logout; leave streaming bodies untouched."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not scope["path"].startswith("/api/"):
            return await self.app(scope, receive, send)

        async def private_send(message):
            if message["type"] == "http.response.start":
                MutableHeaders(scope=message)["cache-control"] = "private, no-store"
            await send(message)
        await self.app(scope, receive, private_send)


app.add_middleware(_PrivateApiResponses)

# CORS chỉ bật khi người dùng chủ ý chạy giao diện ở origin khác. Mặc định tắt:
# server nghe ở 127.0.0.1 và trang web ngoài không được phép gọi vào.
_origins = [o.strip() for o in os.environ.get("VSUB_CORS_ORIGINS", "").split(",") if o.strip()]
if _origins:
    from fastapi.middleware.cors import CORSMiddleware

    app.add_middleware(
        CORSMiddleware, allow_origins=_origins, allow_credentials=True, allow_methods=["*"], allow_headers=["*"]
    )

app.include_router(auth.router)
for router in (system.router, tts.router, ai.router, media.router, jobs.router, films.router, projects.router, collaboration.router):
    app.include_router(router, dependencies=[Depends(access.request_space)])


@app.exception_handler(HTTPException)
async def http_error(request: Request, exc: HTTPException):
    return JSONResponse({"error": exc.detail}, status_code=exc.status_code)


@app.exception_handler(ScriptChanged)
async def script_conflict(request: Request, exc: ScriptChanged):
    return JSONResponse({"error": str(exc)}, status_code=409)


# ------------------------------------------------------------ giao diện

# no-cache: luôn hỏi lại server, tránh chuyện sửa code mà trình duyệt vẫn
# chạy bản cũ trong cache (chỉ tốn 1 request 304 nếu file không đổi).
_NO_CACHE = {"Cache-Control": "no-cache"}
_ASSET_RE = re.compile(r'((?:src|href)=")(/(?:js|css)/[^"?]+|/config\.js)(")')


def _stamp(path: str) -> str:
    try:
        return str(int((FRONTEND_DIR / path.lstrip("/")).stat().st_mtime))
    except OSError:
        return "0"


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def index() -> HTMLResponse:
    html = (FRONTEND_DIR / "index.html").read_text(encoding="utf-8")
    # Gắn thời điểm sửa file vào từng js/css: sửa code là URL đổi theo, trình
    # duyệt buộc phải tải bản mới thay vì dùng bản cũ trong cache.
    html = _ASSET_RE.sub(
        lambda m: f"{m.group(1)}{m.group(2)}?v={_stamp(m.group(2))}{m.group(3)}", html
    )
    return HTMLResponse(html, headers=_NO_CACHE)


def _frontend_file(sub: str, name: str, mime: str) -> FileResponse:
    safe = safe_id(name)
    path = (FRONTEND_DIR / sub / safe) if sub else (FRONTEND_DIR / safe)
    if not safe or not path.is_file():
        raise HTTPException(404, "Không có file này.")
    return FileResponse(path, media_type=mime, headers=_NO_CACHE)


@app.get("/config.js", include_in_schema=False)
def frontend_config() -> FileResponse:
    return _frontend_file("", "config.js", "application/javascript")


@app.get("/js/{name}", include_in_schema=False)
def frontend_js(name: str) -> FileResponse:
    return _frontend_file("js", name, "application/javascript")


@app.get("/css/{name}", include_in_schema=False)
def frontend_css(name: str) -> FileResponse:
    return _frontend_file("css", name, "text/css")


if (FRONTEND_DIR / "assets").is_dir():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIR / "assets"), name="assets")
