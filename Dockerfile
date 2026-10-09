# --- frontend build ---
FROM oven/bun:1.4.2 AS web
WORKDIR /web
COPY frontend/package.json frontend/bun.lock ./
RUN bun install --frozen-lockfile
COPY frontend/ .
RUN bun run build

# --- runtime ---
FROM python:3.12-slim
# FLAVOR=full (default) adds LibreOffice, Pandoc and ffmpeg (~1.5 GB larger).
# FLAVOR=slim keeps PDF / image / OCR tools; tools whose binaries are missing hide themselves.
ARG FLAVOR=full
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr tesseract-ocr-eng tesseract-ocr-spa \
    ghostscript qpdf unpaper pngquant \
    libmagic1 libheif1 \
    && if [ "$FLAVOR" = "full" ]; then \
    apt-get install -y --no-install-recommends \
    libreoffice-writer libreoffice-calc libreoffice-impress \
    pandoc ffmpeg fonts-liberation fonts-dejavu-core; \
    fi \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
WORKDIR /app
# EXTRAS: optional Python extras, e.g. "--extra bedrock --extra transcribe --extra remove-bg"
ARG EXTRAS=""
COPY backend/pyproject.toml backend/uv.lock* ./
RUN uv sync --no-dev --no-install-project $EXTRAS
COPY backend/ .
COPY --from=web /web/dist ./static

RUN useradd -m toolbox && mkdir -p /data /inbox && chown toolbox /data /inbox
USER toolbox
ENV TOOLBOX_DATA_DIR=/data \
    TOOLBOX_STATIC_DIR=/app/static \
    UV_PYTHON_DOWNLOADS=never \
    PATH="/app/.venv/bin:$PATH"
EXPOSE 8080
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
