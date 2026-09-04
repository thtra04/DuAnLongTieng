"""/api/system — trạng thái hệ thống lúc mở trang; /api/translation-cache."""

from __future__ import annotations

import os

from fastapi import APIRouter

from ..config import AI_MODELS, ASR_MODELS, DEFAULT_ASR_MODEL, MAX_UPLOAD_BYTES
from ..core import diarize, dubbing, media, translate
from ..core.languages import LANGUAGES
from ..core.subtitles import DEFAULT_STYLE

router = APIRouter(prefix="/api", tags=["system"])


@router.get("/system")
def system_info() -> dict:
    from ..core import asr

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


@router.get("/translation-cache")
def translation_cache_info() -> dict:
    return translate.cache_info()


@router.delete("/translation-cache")
def translation_cache_clear() -> dict:
    return {"deleted": translate.clear_cache()}
