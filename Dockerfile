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

# Copy application code
COPY ./app ./

RUN addgroup --system --gid 900 app && \
    adduser --system --uid 900 --ingroup app app

RUN chown -R app /app

USER app

CMD ["/app/scripts/start_app.sh"]

########################################################################
#
# Production stage -- minimal runtime image
#
FROM python:${PYTHON_VERSION}-slim AS prod

LABEL org.opencontainers.image.source=https://github.com/scanner/mibudge
LABEL org.opencontainers.image.description="mibudge Personal Budgeting Service"

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

ARG APP_HOME=/app
WORKDIR ${APP_HOME}

# Install ONLY runtime dependencies
RUN apt-get update && \
    apt-get install --assume-yes --no-install-recommends \
    libpq5 \
    gettext \
    && apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Copy the cleaned venv from builder (production deps only)
COPY --from=builder /venv /venv

# Copy pyproject.toml for package metadata
COPY --from=builder /app/pyproject.toml ./pyproject.toml

ENV PATH=/venv/bin:$PATH

# Copy application code
COPY ./app ./

# Provided at build time so collectstatic can load settings.
# Never written to ENV so it is not present at runtime.
ARG SALT_KEY

# Collect static files and pre-compile bytecode
RUN /venv/bin/python /app/manage.py collectstatic --no-input && \
    /venv/bin/python -m compileall /venv

RUN addgroup --system --gid 900 app && \
    adduser --system --uid 900 --ingroup app app

RUN chown -R app /app/staticfiles

USER app

CMD ["/app/scripts/start_app.sh"]
