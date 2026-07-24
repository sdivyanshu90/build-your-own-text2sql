# syntax=docker/dockerfile:1
# =============================================================================
# Multi-stage build. Stage 1 installs the package into an isolated virtualenv;
# stage 2 is a minimal, non-root runtime that copies only the venv + runtime
# assets. This keeps the final image small and free of build toolchains.
# =============================================================================

# ----------------------------- Builder --------------------------------------
FROM python:3.12-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build

# Copy metadata + source, then install (with the postgres driver for prod).
COPY pyproject.toml README.md ./
COPY src ./src

RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --upgrade pip \
    && /opt/venv/bin/pip install ".[postgres]"

# ----------------------------- Runtime --------------------------------------
FROM python:3.12-slim AS runtime

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    T2SQL_API_HOST=0.0.0.0 \
    T2SQL_API_PORT=8000

# Create a non-root user to run the service.
RUN groupadd --system app && useradd --system --gid app --home /app app

WORKDIR /app

COPY --from=builder /opt/venv /opt/venv
# Runtime assets not part of the wheel (migrations, alembic config, scripts).
COPY alembic.ini ./alembic.ini
COPY migrations ./migrations
COPY scripts ./scripts
COPY src ./src

RUN mkdir -p /app/data && chown -R app:app /app
USER app

EXPOSE 8000

# Liveness check without needing curl in the image.
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; \
    sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health/live').status==200 else 1)"

CMD ["uvicorn", "text_to_sql.main:app", "--host", "0.0.0.0", "--port", "8000"]
