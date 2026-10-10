# syntax=docker/dockerfile:1.7
FROM python:3.13-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1
WORKDIR /app

FROM base AS build
COPY --from=ghcr.io/astral-sh/uv:0.11.32 /uv /usr/local/bin/uv
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY . .

FROM base AS runtime
RUN useradd --system --uid 10001 app
COPY --from=build /app /app
ENV PATH="/app/.venv/bin:$PATH" DJANGO_SETTINGS_MODULE=config.settings
USER app
EXPOSE 8000
# One image, several process types (doc 02 §3); the command is chosen by the deploy tool.
CMD ["python", "-m", "uvicorn", "config.asgi:application", "--host", "0.0.0.0", "--port", "8000"]
