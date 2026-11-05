FROM node:24-bookworm-slim AS frontend
WORKDIR /app
ENV NEXT_TELEMETRY_DISABLED=1 API_BASE_URL=http://127.0.0.1:8000
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/next.config.ts frontend/next-env.d.ts frontend/tsconfig.json ./
COPY frontend/src ./src
RUN npm run build

FROM ghcr.io/astral-sh/uv:0.13.6 AS uv
FROM node:24-bookworm-slim AS node
FROM python:3.12-slim-bookworm
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never PATH="/app/.venv/bin:$PATH" NEXT_TELEMETRY_DISABLED=1
WORKDIR /app
COPY --from=uv /uv /bin/uv
COPY --from=node /usr/local/bin/node /usr/local/bin/node
RUN apt-get update && apt-get install -y --no-install-recommends nginx util-linux \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --uid 10001 --create-home app \
    && install -d -o app -g app /app/storage/pdfs
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY backend/app ./app
COPY backend/migrations ./migrations
COPY backend/alembic.ini ./
COPY --from=frontend /app/.next/standalone /web
COPY --from=frontend /app/.next/static /web/.next/static
COPY deploy/nginx.conf deploy/render-start.sh /opt/securerag/
CMD ["bash", "/opt/securerag/render-start.sh"]
