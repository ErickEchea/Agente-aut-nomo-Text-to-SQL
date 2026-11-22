# syntax=docker/dockerfile:1.7
# Build context: repository root (needs backend/ and data/).

FROM ghcr.io/astral-sh/uv:0.13.9 AS uv

FROM python:3.15.2-slim-trixie AS builder
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

FROM python:3.15.2-slim-trixie AS runtime
# OS security fixes published after the base image was built (scanned in CI with Trivy). pip is
# removed: nothing installs packages at runtime, and its vendored libraries carry their own CVEs.
RUN apt-get update \
 && apt-get -y upgrade \
 && rm -rf /var/lib/apt/lists/* \
 && python -m pip uninstall --yes --no-cache-dir pip \
 && groupadd --system nexus && useradd --system --gid nexus --home-dir /app --no-create-home nexus
COPY --from=builder /opt/venv /opt/venv
COPY data /app/data
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
USER nexus
EXPOSE 8000
# nginx is the only way in (the API port is not published to the host) and it overwrites
# X-Forwarded-For with the real client address, so per-IP rate limits see real clients.
CMD ["uvicorn", "nexus.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--no-access-log", "--proxy-headers", "--forwarded-allow-ips", "*"]
