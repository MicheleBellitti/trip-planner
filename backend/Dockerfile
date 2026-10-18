# Trip Planner backend image, built by Railway from the root directory backend/ (the build
# context is backend/ only). One image serves both Railway services:
#   - web:     the default CMD below (uvicorn, one process; railway.json)
#   - cleanup: start command `python -m app.jobs cleanup` on a cron (railway.cron.json)
# Migrations are not run here: Railway's pre-deploy command `alembic upgrade head` runs them in
# a separate container from this image before the web service starts. See docs/deploy.md.
#
# Local build check (from the repo root): docker build -t trip-planner-backend backend

ARG PYTHON_IMAGE=python:3.12-slim-trixie
ARG UV_IMAGE=ghcr.io/astral-sh/uv:0.13.0

FROM ${UV_IMAGE} AS uv

# ---- build: resolve the locked runtime dependencies into /app/.venv -------------------------
FROM ${PYTHON_IMAGE} AS build

COPY --from=uv /uv /usr/local/bin/uv

# Use the image's CPython (never download one) and compile bytecode once at build time. No
# BuildKit cache mount: Railway accepts one only with an `id=s/<service id>-...` prefix, which
# differs per service; the layer cache below does the same job.
ENV UV_PYTHON_DOWNLOADS=never \
    UV_PYTHON=/usr/local/bin/python3.12 \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    UV_COMPILE_BYTECODE=1 \
    UV_NO_CACHE=1

WORKDIR /app

# Only the lock and the project metadata decide this layer, so code changes reuse it.
# `--no-dev`: ruff, pyright, pytest and friends never reach the image. The project itself is
# not a package (`[tool.uv] package = false`): this installs dependencies only.
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project

# ---- runtime ------------------------------------------------------------------------------
FROM ${PYTHON_IMAGE} AS runtime

# A fixed, unprivileged user. The code stays owned by root, so the process cannot rewrite it.
RUN groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app --home-dir /home/app --create-home \
       --shell /usr/sbin/nologin app

WORKDIR /app

# The virtualenv lives at the same path as in the build stage (venvs are not relocatable) and
# points at the same /usr/local/bin/python3.12 of the same base image.
COPY --from=build /app/.venv /app/.venv

# Everything the backend reads at runtime: the package, the migrations, alembic.ini, the
# per-profile lockfiles written by `ant apply` (backend/claude-lock.<profile>.json) and the
# pinned TripTracker schema backend/pinned/trip.schema.json, which production reads with
# TRIP_SCHEMA_URL=file:///app/pinned/trip.schema.json until TripTracker serves
# /schema/trip.json (docs/deploy.md). .dockerignore keeps tests/ and the rest out.
COPY . /app

# Fail the build, not the first plan, if the pinned schema went missing from the context.
# Drop this line together with backend/pinned/ once TRIP_SCHEMA_URL is unset in production.
RUN test -s /app/pinned/trip.schema.json

# FORWARDED_ALLOW_IPS: Railway's edge proxy sends X-Forwarded-Proto/For from an address that is
# not 127.0.0.1, and uvicorn trusts proxy headers only from the addresses listed here. The
# container is reachable only through that proxy. PORT is a local default; Railway injects its
# own.
ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    FORWARDED_ALLOW_IPS="*" \
    PORT=8000

# Numeric, so a platform can check it is not root without resolving names.
USER 10001:10001

EXPOSE 8000

# One uvicorn process, never --workers: the live SSE channel and the plan consumers are in
# memory, so the service runs as exactly one process on one replica. Railway injects PORT.
# --proxy-headers: https scheme from Railway's proxy. With FORWARDED_ALLOW_IPS="*" uvicorn also
#   sets request.client to the LEFTMOST X-Forwarded-For value, which the client chose: nothing
#   may trust it. The rate limits key on the last value instead (TRUST_PROXY_HEADERS, on by
#   default in production; app/ratelimit.py), so it must not be turned off on Railway.
# --no-access-log: access lines carry client IPs (personal data); the app logs structlog JSON.
# --timeout-graceful-shutdown: open SSE streams would otherwise hold a redeploy until SIGKILL;
#   after 20 s they are closed and the lifespan shutdown stops the consumers cleanly (Railway
#   drainingSeconds is 30, see railway.json).
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port \"${PORT}\" --proxy-headers --no-access-log --timeout-graceful-shutdown 20"]
