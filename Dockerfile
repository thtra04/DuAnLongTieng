# === Stage 1: builder — cài dependencies với uv ===
FROM python:3.12-slim AS builder

RUN pip install --no-cache-dir uv

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --no-dev --frozen --no-install-project

# === Stage 2: runtime ===
FROM python:3.12-slim

# ffmpeg + ffprobe cho xử lý media
RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY --from=builder /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1
ENV PYTHONIOENCODING=utf-8

COPY backend/ backend/
COPY frontend/ frontend/
COPY training/ training/
COPY run.py .
COPY pyproject.toml .

# Dữ liệu lưu ở volume, không ghi vào image
ENV VSUB_DATA_DIR=/data
VOLUME /data

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/system')" || exit 1

CMD ["python", "run.py", "--host", "0.0.0.0", "--no-browser"]
