# Fijada por digest (python 3.12.16, descargada el 11 de noviembre de 2026) para que la imagen sea reproducible.
ARG PYTHON_IMAGE=python:3.12-slim@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b
# Node para promptfoo (tarea 15), que pide Node >= 22.22. 22.23.3 sobre Debian 13, como la base de Python;
# publicada el 21 de octubre de 2026.
ARG NODE_IMAGE=node:22.23.3-trixie-slim@sha256:28d03803f09ba76560e273af33beb7eda4ed68fa0698bc9bd15e9a6e35693923

FROM ${NODE_IMAGE} AS node

# --- Dependencias de Python, comunes a las apps y al arnés -----------------------------------
FROM ${PYTHON_IMAGE} AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_COMPILE_BYTECODE=1 \
    PATH="/opt/venv/bin:${PATH}" \
    ANONYMIZED_TELEMETRY=False

RUN pip install --no-cache-dir uv==0.13.7

WORKDIR /app
COPY pyproject.toml uv.lock ./
# Incluye el grupo dev (pytest, Playwright): el arnés lo usa y así las dos imágenes comparten esta capa.
RUN uv sync --frozen --no-install-project

RUN useradd --create-home --uid 10001 lab \
    && mkdir -p /data /app/attacks /app/results \
    && chown -R lab:lab /data /app/attacks /app/results

# --- Arnés: runner, tests con modelo, oráculo de V5 y promptfoo ------------------------------
# Las apps no necesitan navegador ni Node, así que esto queda fuera de su imagen.
FROM base AS harness

ENV PLAYWRIGHT_BROWSERS_PATH=/opt/ms-playwright \
    PROMPTFOO_DISABLE_TELEMETRY=1 \
    PROMPTFOO_DISABLE_REMOTE_GENERATION=true \
    PROMPTFOO_DISABLE_UPDATE=1

# El Chromium headless que espera la versión de Playwright de uv.lock (oráculo xss_executed),
# con sus bibliotecas del sistema. El node que trae Playwright (y el de promptfoo) necesita libatomic1.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libatomic1 \
    && playwright install --with-deps --only-shell chromium \
    && rm -rf /var/lib/apt/lists/* \
    && chmod -R a+rX /opt/ms-playwright

COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && ln -s ../lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx \
    && npm install -g --no-fund --no-audit promptfoo@0.125.1 \
    && npm cache clean --force

COPY app ./app
COPY data ./data
COPY tests ./tests
COPY scripts ./scripts

USER lab
CMD ["pytest", "-m", "llm", "-v"]

# --- Apps (vulnerable y segura). Va última: `docker build .` arma esta imagen. ----------------
FROM base AS app

COPY app ./app
COPY data ./data
COPY scripts ./scripts

USER lab
EXPOSE 8000
CMD ["uvicorn", "--factory", "app.main:app_from_env", "--host", "0.0.0.0", "--port", "8000"]
