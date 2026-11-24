# BILEKSA HVAC backend (Railway, Render or Cloud Run build this image)
FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY --from=ghcr.io/astral-sh/uv:0.8 /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./
RUN useradd --system --uid 10001 bileksa && chown -R bileksa /app
USER bileksa
ENV PATH="/app/.venv/bin:$PATH" ENVIRONMENT=production
EXPOSE 8000
# Migrations normally run as a separate release step (railway.json preDeployCommand). Hosts
# without release steps (Render free, Cloud Run) set RUN_MIGRATIONS_ON_START=true instead;
# migrations are additive and safe to repeat. One instance only (decision: single replica).
CMD ["sh", "-c", "if [ \"$RUN_MIGRATIONS_ON_START\" = true ]; then alembic upgrade head || exit 1; fi; exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]
