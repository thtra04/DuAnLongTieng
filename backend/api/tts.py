"""/api/tts — danh sách giọng và đọc thử."""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from ..config import DATA_DIR
from ..core import dub_review, dubbing
from ..core.subtitles import Cue
from .deps import edited_cues

router = APIRouter(prefix="/api/tts", tags=["tts"])


@router.get("/voices")
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


@router.post("/preview")
def tts_preview(payload: dict):
    ok, reason = dubbing.available()
    if not ok:
        raise HTTPException(400, reason)
    text = (payload.get("text") or "").strip()
    voice = payload.get("voice") or ""
    if voice == dubbing.CLONE_VOICE:
        raise HTTPException(
            400, "Giọng nhân bản cần mẫu từ video. Mở dự án và chọn “Xem & nghe” cạnh câu cần thử."
        )
    out = DATA_DIR / "preview"
    out.mkdir(parents=True, exist_ok=True)
    temp = TemporaryDirectory(dir=out)
    path = Path(temp.name) / "preview.wav"
    try:
        dubbing.preview(text, voice=voice, style=payload.get("style") or "tu_nhien", out_path=path)
    except Exception as exc:
        temp.cleanup()
        raise HTTPException(500, f"Không đọc thử được: {exc}") from exc
    return FileResponse(path, media_type="audio/wav", headers={"Cache-Control": "no-store"},
                        background=BackgroundTask(temp.cleanup))


@router.post("/script")
def tts_script(payload: dict) -> dict:
    """Kịch bản lồng tiếng: đúng các câu sẽ được đọc lúc xuất, đã đặt dấu câu.

    Có `project`: mỗi mốc phụ đề có một câu đọc riêng để xem, sửa và duyệt.
    Không có dự án: dựng các cụm câu liền mạch để thử độc lập.
    """
    cues = [Cue.from_dict(c) for c in edited_cues(payload.get("cues") or [], allow_blank=True)]
    if not cues:
        return {"units": []}
    return dub_review.draft(cues, payload.get("project"), payload.get("source_lang"),
                            payload.get("target_lang"), payload.get("shorten", False))
