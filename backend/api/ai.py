"""/api/ai — kiểm tra kết nối engine AI (Claude / OpenAI-compatible).

Key đi cùng request y như lúc gửi `/api/analyze`, dùng xong là bỏ: không ghi log,
không lưu file. Trả về lỗi API dưới dạng dữ liệu (ok=false) chứ không ném 5xx,
vì chính dòng lỗi đó là thứ người dùng cần đọc: key sai, model không tồn tại,
endpoint chậm...
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..core import translate

router = APIRouter(prefix="/api/ai", tags=["ai"])


@router.post("/check")
def ai_check(payload: dict) -> dict:
    data = payload or {}
    engine = str(data.get("engine") or "").strip()
    if engine not in ("claude", "openai"):
        raise HTTPException(400, "Chỉ kiểm tra được engine Claude hoặc OpenAI (các engine khác không cần key).")
    ok, why = translate.engine_available(engine)
    if not ok:
        raise HTTPException(400, why)
    return translate.check_connection(
        engine,
        api_key=str(data.get("api_key") or ""),
        model=str(data.get("ai_model") or "").strip(),
        base_url=str(data.get("ai_base_url") or "").strip(),
    )
