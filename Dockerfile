ARG PYTHON_VERSION=3.13

########################################################################
#
# Builder stage -- compile dependencies into /venv
#
FROM python:${PYTHON_VERSION}-slim AS builder

ARG APP_HOME=/app
WORKDIR ${APP_HOME}

# Install build dependencies needed to compile Python packages with C extensions
RUN apt-get update && \
    apt-get install --assume-yes --no-install-recommends \
    gcc \
    g++ \
    make \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Copy dependency files and install deps only (not project) -- cached layer
COPY pyproject.toml uv.lock ./
ENV UV_PROJECT_ENVIRONMENT=/venv
RUN uv sync --frozen --no-dev --no-install-project

# Clean up unnecessary files from venv to reduce size.
# NOTE: Only remove 'tests' (plural) -- third-party test suites live there.
# Do NOT remove 'test' (singular): django/test/ is a core Django module.
RUN find /venv -type d -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true && \
    find /venv -type d -name 'tests' -prune -exec rm -rf {} + 2>/dev/null || true

########################################################################
#
# Frontend builder stage -- build the Vue SPA with pnpm
#
FROM node:22-slim AS frontend-builder

WORKDIR /frontend

# pnpm 9.x matches the lockfile format (lockfileVersion: '9.0')
RUN npm install -g pnpm@9

# Install dependencies (cached layer)
COPY frontend/package.json frontend/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

# Build the production bundle
COPY frontend/ ./
RUN pnpm build

########################################################################
#
# Development stage -- includes dev dependencies and debugging tools
#
FROM python:${PYTHON_VERSION}-slim AS dev

LABEL org.opencontainers.image.source=https://github.com/scanner/mibudge
LABEL org.opencontainers.image.description="mibudge Personal Budgeting Service (Development)"

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

ARG APP_HOME=/app
WORKDIR ${APP_HOME}

# Install runtime dependencies + build tools + development tools
RUN apt-get update && \
    apt-get install --assume-yes --no-install-recommends \
    libpq5 \
    gcc \
    g++ \
    make \
    libpq-dev \
    gettext \
    vim \
    git \
    procps \
    && apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Copy the production venv from builder
COPY --from=builder /venv /venv

# Copy dependency files and sync with dev dependencies
COPY pyproject.toml uv.lock ./
ENV UV_PROJECT_ENVIRONMENT=/venv
RUN uv sync --frozen --no-install-project

ENV PATH=/venv/bin:$PATH

# Prevent uv from syncing or caching at runtime -- deps are frozen in /venv
ENV UV_NO_SYNC=1 \
    UV_NO_CACHE=1

# Copy application code
COPY ./app ./

# Include the built frontend so the dev image is self-contained.
# Local dev still uses the Vite dev server (DJANGO_VITE_DEV_MODE=True), but
# the image can also run with dev mode off (e.g. staging smoke-tests).
COPY --from=frontend-builder /frontend/dist /frontend/dist

RUN addgroup --system --gid 900 app && \
    adduser --system --uid 900 --ingroup app app

RUN chown -R app /app

USER app

CMD ["/app/scripts/start_dev.sh"]

########################################################################
#
# Production stage -- nginx + gunicorn in a single deployable unit.
#
# nginx (port 8000) serves /static/ directly from the collected staticfiles
# and proxies all other requests to gunicorn via a Unix socket.
# supervisord manages both processes.
#
FROM python:${PYTHON_VERSION}-slim AS prod

LABEL org.opencontainers.image.source=https://github.com/scanner/mibudge
LABEL org.opencontainers.image.description="mibudge Personal Budgeting Service"

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

ARG APP_HOME=/app
WORKDIR ${APP_HOME}

# Install runtime dependencies, nginx, and supervisor
RUN apt-get update && \
    apt-get install --assume-yes --no-install-recommends \
    libpq5 \
    gettext \
    nginx \
    supervisor \
    && apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Copy the cleaned venv from builder (production deps only)
COPY --from=builder /venv /venv

# Copy pyproject.toml for package metadata
COPY --from=builder /app/pyproject.toml ./pyproject.toml

ENV PATH=/venv/bin:$PATH

# Copy application code
COPY ./app ./

# Copy built frontend assets from the frontend builder stage.
# NOTE: REPO_DIR in settings.py resolves to the parent of /app (i.e. /),
# so the frontend dist must land at /frontend/dist for collectstatic to find it.
COPY --from=frontend-builder /frontend/dist /frontend/dist

# Provided at build time so collectstatic can load settings.
# Never written to ENV so it is not present at runtime.
ARG SALT_KEY

# Collect static files (Django app + built frontend assets) and pre-compile bytecode
RUN DJANGO_VITE_DEV_MODE=False /venv/bin/python /app/manage.py collectstatic --no-input && \
    /venv/bin/python -m compileall /venv

# Install nginx and supervisord configuration
COPY deployment/nginx.conf /etc/nginx/nginx.conf
COPY deployment/supervisord.conf /etc/supervisor/supervisord.conf

RUN addgroup --system --gid 900 app && \
    adduser --system --uid 900 --ingroup app app

RUN chown -R app /app/staticfiles

EXPOSE 8000

# supervisord manages nginx (as root) and gunicorn (as app user)
CMD ["/usr/bin/supervisord", "-c", "/etc/supervisor/supervisord.conf"]
