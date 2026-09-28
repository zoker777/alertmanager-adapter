FROM ghcr.io/astral-sh/uv:0.11.21 AS uv
FROM python:3.12-slim
COPY --from=uv /uv /uvx /bin/
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 CONFIG_PATH=/app/config/config.yaml \
    UV_PYTHON_DOWNLOADS=never UV_LINK_MODE=copy PATH="/app/.venv/bin:$PATH"
WORKDIR /app
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-dev \
    && groupadd --system --gid 10001 adapter && useradd --system --uid 10001 --gid 10001 adapter
COPY --chown=10001:10001 app ./app
COPY --chown=10001:10001 config ./config
USER adapter
EXPOSE 8080
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
