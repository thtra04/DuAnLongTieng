"""/api/ai — kiểm tra kết nối engine AI (Claude / OpenAI-compatible).

Key đi cùng request y như lúc gửi `/api/analyze`, dùng xong là bỏ: không ghi log,
không lưu file. Trả về lỗi API dưới dạng dữ liệu (ok=false) chứ không ném 5xx,
vì chính dòng lỗi đó là thứ người dùng cần đọc: key sai, model không tồn tại,
endpoint chậm...
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..core import hanviet, translate, zh_terms

router = APIRouter(prefix="/api/ai", tags=["ai"])


@router.post("/terms")
def suggest_terms(payload: dict) -> dict:
    texts = payload.get("texts")
    if (not isinstance(texts, list) or len(texts) > 20000 or
        not all(isinstance(t, str) for t in texts) or sum(map(len, texts)) > 300000):
        raise HTTPException(400, "Kịch bản quá dài hoặc không hợp lệ.")
    if not hanviet.enabled(str(payload.get("source_lang")), str(payload.get("target_lang"))):
        raise HTTPException(400, "Gợi ý Hán Việt cần chọn tiếng Trung → tiếng Việt.")
    existing = dict(translate.parse_glossary(str(payload.get("glossary") or "")))
    return {"terms": [r for r in zh_terms.Lexicon(texts, existing.items()).suggest(texts) if r["zh"] not in existing]}


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
