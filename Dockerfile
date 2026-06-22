FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    git \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

COPY pyproject.toml uv.lock README.md ./
COPY src ./src
COPY web ./web
COPY config.default.toml ./

RUN uv sync --frozen --no-dev --extra chat

ENV PATH="/app/.venv/bin:$PATH" \
    HOST=0.0.0.0 \
    HERETIC_QUANTIZATION=bnb_4bit \
    HERETIC_MAX_RESPONSE_LENGTH=4096

EXPOSE 8000

CMD ["heretic-chat"]
