"""Đường dẫn & cấu hình dùng chung."""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB_DIR = ROOT / "web"
DATA_DIR = Path(os.environ.get("VSUB_DATA_DIR", ROOT / "data"))
UPLOAD_DIR = DATA_DIR / "uploads"
JOB_DIR = DATA_DIR / "jobs"
MODEL_DIR = Path(os.environ.get("VSUB_MODEL_DIR", DATA_DIR / "models"))
TOOLS_DIR = ROOT / "tools"

for _d in (DATA_DIR, UPLOAD_DIR, JOB_DIR, MODEL_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# Kích thước file upload tối đa (bytes) — 4 GB
MAX_UPLOAD_BYTES = int(os.environ.get("VSUB_MAX_UPLOAD", 4 * 1024**3))

# Model Whisper mặc định
DEFAULT_ASR_MODEL = os.environ.get("VSUB_ASR_MODEL", "medium")

ASR_MODELS = [
    {"id": "tiny", "label": "Tiny — nhanh nhất, độ chính xác thấp", "size": "~75 MB"},
    {"id": "base", "label": "Base — nhanh, tạm ổn", "size": "~145 MB"},
    {"id": "small", "label": "Small — cân bằng", "size": "~490 MB"},
    {"id": "medium", "label": "Medium — chính xác tốt (khuyến nghị)", "size": "~1.5 GB"},
    {"id": "large-v3", "label": "Large v3 — chính xác nhất, chậm hơn", "size": "~3.1 GB"},
]

AI_MODELS = {
    "anthropic": [
        {"id": "claude-opus-5", "label": "Claude Opus 5 (mạnh nhất)"},
        {"id": "claude-sonnet-5", "label": "Claude Sonnet 5 (nhanh, rẻ hơn)"},
        {"id": "claude-haiku-4-5", "label": "Claude Haiku 4.5 (rẻ nhất)"},
    ],
    "openai": [
        {"id": "kr/claude-opus-5-thinking-agentic", "label": "9Router · Claude Opus 5 Thinking Agentic"},
        {"id": "kr/claude-sonnet-5", "label": "9Router · Claude Sonnet 5"},
        {"id": "kr/claude-haiku-4.5", "label": "9Router · Claude Haiku 4.5"},
        {"id": "kr/deepseek-3.2", "label": "9Router · DeepSeek 3.2"},
        {"id": "kr/qwen3-coder-next", "label": "9Router · Qwen3 Coder Next"},
        {"id": "kr/glm-5", "label": "9Router · GLM 5"},
        {"id": "kr/MiniMax-M2.5", "label": "9Router · MiniMax M2.5"},
        {"id": "gpt-4o", "label": "OpenAI · GPT-4o"},
        {"id": "gpt-4o-mini", "label": "OpenAI · GPT-4o mini"},
    ],
}
