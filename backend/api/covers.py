"""Decode library uploads into small, metadata-free JPEGs before storing them."""

from io import BytesIO
from typing import Literal

from fastapi import HTTPException, Request, Response
from PIL import Image, ImageOps
from starlette.concurrency import run_in_threadpool

MAX_BYTES = 5 * 1024 * 1024
MAX_PIXELS = 24_000_000


def _jpeg(raw: bytearray) -> bytes:
    try:
        with Image.open(BytesIO(raw), formats=("JPEG", "PNG", "WEBP")) as source:
            if source.width * source.height > MAX_PIXELS:
                raise HTTPException(413, "Ảnh bìa phải nhỏ hơn hoặc bằng 24 megapixel.")
            source.thumbnail((640, 640), Image.Resampling.LANCZOS)
            rgba = ImageOps.exif_transpose(source).convert("RGBA")
            clean = Image.new("RGB", rgba.size, "#faf7ef")
            clean.paste(rgba, mask=rgba.getchannel("A"))
            out = BytesIO()
            clean.save(out, "JPEG", quality=86)
            return out.getvalue()
    except Image.DecompressionBombError as exc:
        raise HTTPException(413, "Kích thước ảnh quá lớn.") from exc
    except (OSError, ValueError, SyntaxError) as exc:
        raise HTTPException(422, "Không đọc được ảnh. Hãy chọn ảnh JPG, PNG hoặc WebP khác.") from exc


async def cover_choice(request: Request, mode: Literal["upload", "auto"] = "upload") -> bytes | None:
    if mode == "auto":
        return None
    raw = bytearray()
    async for chunk in request.stream():
        if len(raw) + len(chunk) > MAX_BYTES:
            raise HTTPException(413, "Ảnh bìa tối đa 5 MB.")
        raw.extend(chunk)
    return await run_in_threadpool(_jpeg, raw)


def uploaded_cover(jpeg: bytes | None) -> Response:
    if not jpeg:
        raise HTTPException(404, "Chưa có ảnh bìa tải lên.")
    return Response(jpeg, media_type="image/jpeg")
