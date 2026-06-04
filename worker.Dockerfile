# Dockerfile.worker — Wobsongo ingestion worker
#
# Build:
#   docker build -f Dockerfile.worker -t wobsongo-worker .
#
# Run:
#   docker run --env-file .env wobsongo-worker
#
# Required env vars (pass via --env-file or -e):
#   OLLAMA_BASE_URL, OLLAMA_MODEL, OLLAMA_EMBED_MODEL
#   S3_BUCKET, S3_ENDPOINT_URL (omit for AWS)
#   AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY
#   WOBSONGO_DB_PATH  (mount a volume for persistence)
#
# Platform: linux/amd64 only — liteparse ships x86_64 binaries

FROM python:3.14-slim

# tesseract-ocr: required when liteparse OCR mode is enabled.
# eng + fra match the tessdata/ directory in the repo.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        tesseract-ocr \
        tesseract-ocr-eng \
        tesseract-ocr-fra \
    && rm -rf /var/lib/apt/lists/*

# Pin uv to the same version used in devbox for reproducibility
COPY --from=ghcr.io/astral-sh/uv:0.9.21 /uv /usr/local/bin/uv

WORKDIR /app

# Install Python dependencies
# This layer is rebuilt only when pyproject.toml or uv.lock changes.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev \
    --extra pdf \
    --extra ollama \
    --extra storage \
    --extra db

# Application source (separate layer so dep cache survives code changes)
COPY wobsongo/ wobsongo/
COPY tessdata/ tessdata/
COPY worker.py ./

# Activate the venv created by uv sync
ENV PATH="/app/.venv/bin:$PATH" \
    TESSDATA_PREFIX=/app/tessdata \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    WOBSONGO_DB_PATH=/data/wobsongo.db

# Mount a volume at /data to persist the SQLite database across restarts
VOLUME ["/data"]

CMD ["python", "worker.py"]
