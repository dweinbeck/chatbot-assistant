FROM python:3.12-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy

WORKDIR /app

# Install dependencies first (layer caching)
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Copy application code
COPY app/ ./app/
COPY migrations/ ./migrations/
COPY alembic.ini ./

# Sync again to install the project itself
RUN uv sync --frozen --no-dev

# --- Runtime stage ---
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Copy the virtual environment from builder
COPY --from=builder /app/.venv /app/.venv

# Copy application code and migrations
COPY --from=builder /app/app ./app
COPY --from=builder /app/migrations ./migrations
COPY --from=builder /app/alembic.ini ./
COPY scripts/start.sh ./scripts/start.sh

# Add venv to PATH
ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 8080

CMD ["bash", "scripts/start.sh"]
