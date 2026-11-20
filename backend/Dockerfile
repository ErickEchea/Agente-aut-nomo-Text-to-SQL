# syntax=docker/dockerfile:1.7
# Build context: repository root (needs backend/ and data/).

FROM ghcr.io/astral-sh/uv:0.13.9 AS uv

FROM python:3.13.18-slim-trixie AS builder
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv
WORKDIR /src/backend
COPY backend/pyproject.toml backend/uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project
COPY backend/README.md ./
COPY backend/src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable

FROM python:3.13.18-slim-trixie AS runtime
RUN groupadd --system nexus && useradd --system --gid nexus --home-dir /app --no-create-home nexus
COPY --from=builder /opt/venv /opt/venv
COPY data /app/data
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
USER nexus
EXPOSE 8000
CMD ["uvicorn", "nexus.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--no-access-log", "--proxy-headers"]
