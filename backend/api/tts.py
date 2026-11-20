"""/api/tts — danh sách giọng và đọc thử."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from ..config import DATA_DIR
from ..core import dubbing

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


@router.post("/script")
def tts_script(payload: dict) -> dict:
    """Kịch bản lồng tiếng: đúng các câu sẽ được đọc lúc xuất, đã đặt dấu câu.

    Chạy y như lúc xuất (rút gọn bằng luật nếu bật, gộp câu theo người nói) trên
    một bản sao của phụ đề, để người dùng xem và sửa trước khi lồng tiếng. Chữ
    trả về nằm ở `base` — gửi kèm khi xuất để biết bản sửa còn khớp hay đã cũ.
    """
    import copy

    from ..core import budget, shorten
    from ..core.subtitles import Cue

    cues = [Cue.from_dict(c) for c in payload.get("cues") or [] if isinstance(c, dict)]
    if not cues:
        return {"units": []}
    use_translation = any((c.text2 or "").strip() for c in cues)
    target = (payload.get("target_lang") or "vi").lower()
    if use_translation and payload.get("shorten", True) and target.startswith("vi"):
        cues = copy.deepcopy(cues)
        try:
            budget.run_loop(cues, shorten.make_tightener())
        except Exception:
            pass
    units = dubbing.speech_units(cues, use_translation)
    return {
        "use_translation": use_translation,
        "units": [
            {"cues": u["cues"], "start": round(u["start"], 3), "end": round(u["end"], 3),
             "speaker": u["speaker"], "text": u["text"]}
            for u in units
        ],
    }
