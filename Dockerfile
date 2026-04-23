# Resume Agent — FastAPI + Playwright (Chromium) for job scrapers.
# Runtime state (SQLite, artifacts, browser profiles) lives under /data — mount a volume or EFS.

FROM python:3.12-slim-bookworm

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    OUTPUTS_DIR=/data/outputs \
    PLAYWRIGHT_PROFILES_DIR=/data/playwright \
    PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers

COPY requirements.txt .

RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /opt/pw-browsers /data/outputs /data/playwright \
    && pip install --no-cache-dir -r requirements.txt \
    && playwright install --with-deps chromium \
    && chown -R appuser:appuser /opt/pw-browsers /data

COPY app ./app
COPY data ./data
COPY scripts ./scripts

RUN chown -R appuser:appuser /app

USER appuser
EXPOSE 8000
VOLUME ["/data"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=3)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
