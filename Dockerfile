# syntax=docker/dockerfile:1
# One image, two processes: `app` (API + built SPA) and `oncall-agent`
# (`python -m app.oncall`). Stage 1 builds the React bundle; stage 2 is the
# Python runtime that serves it.

# ---- stage 1: frontend bundle ------------------------------------------------
FROM node:22-alpine AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run build

# ---- stage 2: python runtime -------------------------------------------------
FROM python:3.12-slim AS runtime

# Build argument -> `version` on /api/health. CI passes the commit SHA.
ARG APP_VERSION=dev
ENV APP_VERSION=${APP_VERSION} \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PATH="/app/.venv/bin:${PATH}"

COPY --from=ghcr.io/astral-sh/uv:0.6.14 /uv /uvx /bin/

WORKDIR /app

# Dependencies first so they cache independently of the source.
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-dev --no-install-project

COPY alembic.ini ./
COPY alembic/ ./alembic/
COPY app/ ./app/
COPY --from=web /web/dist/ ./app/static/

RUN useradd --system --uid 10001 --home /app ciw && chown -R ciw:ciw /app
USER ciw

EXPOSE 8000

# Migrations run before the server starts; the worker overrides this command.
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port 8000"]
