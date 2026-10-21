FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.8.22 /uv /uvx /bin/
ENV PYTHONUNBUFFERED=1 UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
WORKDIR /app
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --locked --no-dev
COPY app ./app
ENV PATH="/app/.venv/bin:$PATH"
# Single worker on purpose: the scheduler runs in-process.
# PORT comes from .env (default 8000); exec keeps uvicorn as PID 1 so it gets stop signals.
ENV PORT=8000
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port \"$PORT\" --workers 1 --proxy-headers"]
