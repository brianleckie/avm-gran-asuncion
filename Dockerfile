# API del AVM en Railway (F13). Uso: ver docs/deploy.md.
FROM python:3.12-slim

# Runtime OpenMP usado por la rueda Linux de LightGBM.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Misma versión de uv que el desarrollo (uv --version).
COPY --from=ghcr.io/astral-sh/uv:0.13.5 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH" \
    # Por defecto producción: AVM_PREDICTOR=fake queda prohibido aunque falte la variable en Railway.
    AVM_ENV=production

WORKDIR /app

# Capa de dependencias: solo se rehace si cambian pyproject.toml o uv.lock.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# README.md lo exige el `readme` de pyproject.toml al instalar el proyecto.
COPY README.md ./
COPY src ./src
# deploy/ siempre existe (tiene un README); deploy/model/ solo cuando hay modelo (ADR-008).
COPY deploy ./deploy
RUN uv sync --frozen --no-dev

RUN useradd --system --no-create-home app
USER app

# Railway inyecta $PORT. Un solo worker: el rate limit es en memoria. --no-proxy-headers: la IP del
# cliente se lee solo con AVM_TRUST_PROXY (ver avm.api.ratelimit.client_ip).
CMD ["sh", "-c", "exec uvicorn avm.api.app:app --host 0.0.0.0 --port ${PORT:-8000} --no-proxy-headers"]
