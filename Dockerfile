FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN groupadd --gid 10001 app && useradd --uid 10001 --gid 10001 --create-home app
COPY pyproject.toml README.md ./
COPY app ./app
COPY config ./config
COPY knowledge ./knowledge
COPY templates ./templates
COPY scripts ./scripts
RUN python -m pip install --upgrade pip && pip install . && \
    mkdir -p /app/runtime/tmp /app/runtime/backups && chown -R app:app /app/runtime

USER app

HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
    CMD ["python", "-m", "app.healthcheck"]

CMD ["python", "-m", "app"]
