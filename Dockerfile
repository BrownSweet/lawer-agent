# syntax=docker/dockerfile:1.7
FROM node:22-bookworm-slim AS frontend-builder
WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
ENV VITE_BASE_PATH=/lawer/
RUN npm run build

FROM ghcr.io/astral-sh/uv:0.11.19 AS uv-bin
FROM python:3.12-slim-bookworm AS python-builder
COPY --from=uv-bin /uv /usr/local/bin/uv
WORKDIR /app/law_backend
ENV UV_PROJECT_ENVIRONMENT=/opt/venv UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1
COPY law_backend/pyproject.toml law_backend/uv.lock ./
COPY law_backend/src/ ./src/
RUN uv sync --locked --no-dev

FROM python:3.12-slim-bookworm AS runtime
RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends nginx supervisor ca-certificates tzdata \
    && rm -rf /var/lib/apt/lists/* /etc/nginx/sites-enabled/default
ENV PATH="/opt/venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    TZ=Asia/Shanghai COOKIE_SECURE=true \
    CREWAI_TELEMETRY_ENABLED=false CREWAI_TRACING_ENABLED=false OTEL_SDK_DISABLED=true \
    DATA_DIR=/app/.local/files
WORKDIR /app/law_backend
COPY --from=python-builder /opt/venv /opt/venv
COPY law_backend/src/ ./src/
COPY law_backend/alembic.ini ./
COPY law_backend/migrations/ ./migrations/
COPY --from=frontend-builder /build/frontend/dist /app/frontend/dist
COPY docker/nginx.conf /etc/nginx/conf.d/lawer.conf
COPY docker/supervisord.conf /etc/supervisor/lawer.conf
COPY docker/entrypoint.sh docker/healthcheck.py /app/docker/
RUN chmod +x /app/docker/entrypoint.sh && mkdir -p /app/.local/files && nginx -t
EXPOSE 80
VOLUME ["/app/.local"]
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD ["python", "/app/docker/healthcheck.py"]
ENTRYPOINT ["/app/docker/entrypoint.sh"]
CMD ["/usr/bin/supervisord", "-c", "/etc/supervisor/lawer.conf"]
