"""Đường dẫn & cấu hình dùng chung."""

from __future__ import annotations

import os
from pathlib import Path

# ----------------------------------------------------------- riêng tư
#
# Tắt mọi kênh "gọi về nhà" của thư viện bên thứ ba TRƯỚC khi chúng được nạp —
# module này được import đầu tiên ở khắp nơi nên đặt ở đây là chắc ăn nhất.
# Dùng setdefault: ai cố ý muốn bật thì đặt biến môi trường trước khi chạy.
#
# Rà soát thực tế trên các gói đang cài (9/2026):
#
# * pyannote.audio 4.x có module telemetry riêng, MẶC ĐỊNH BẬT, gửi qua
#   OpenTelemetry tới https://otel.pyannote.ai/v1/traces mỗi lần nạp pipeline
#   và mỗi lần chạy: tên model, phiên bản, một UUID phiên, THỜI LƯỢNG FILE
#   AUDIO của người dùng và số nhân vật yêu cầu. Nó đọc biến này lúc import,
#   nên phải đặt trước.
# * huggingface_hub có send_telemetry (không thấy chỗ nào trong đường chạy
#   của ta gọi tới, nhưng tắt sẵn cho chắc).
# * gradio (kéo theo từ vieneu, ta không import) gửi thống kê tới
#   api.gradio.app lúc launch() — tắt phòng khi có thư viện nào gọi tới.
#
# Những gì VẪN rời khỏi máy khi người dùng chủ động dùng: link video (yt-dlp),
# chữ phụ đề khi chọn engine dịch online, token HF khi tải model — xem README.
for _name, _value in (
    ("PYANNOTE_METRICS_ENABLED", "false"),
    ("HF_HUB_DISABLE_TELEMETRY", "1"),
    ("GRADIO_ANALYTICS_ENABLED", "False"),
    ("DISABLE_TELEMETRY", "1"),
    ("DO_NOT_TRACK", "1"),
):
    os.environ.setdefault(_name, _value)

ROOT = Path(__file__).resolve().parent.parent
FRONTEND_DIR = ROOT / "frontend"
WEB_DIR = FRONTEND_DIR  # tên cũ, giữ cho tương thích
DATA_DIR = Path(os.environ.get("VSUB_DATA_DIR", ROOT / "data"))
UPLOAD_DIR = DATA_DIR / "uploads"
JOB_DIR = DATA_DIR / "jobs"
MODEL_DIR = Path(os.environ.get("VSUB_MODEL_DIR", DATA_DIR / "models"))
# Demucs (tách giọng gốc) tải model qua torch.hub -> trỏ vào thư mục model, đừng để rơi vào ổ C
os.environ.setdefault("TORCH_HOME", str(MODEL_DIR / "torch"))
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
