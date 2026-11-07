ARG PYTHON_IMAGE=python:3.12-slim
FROM ${PYTHON_IMAGE}

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_COMPILE_BYTECODE=1 \
    PATH="/opt/venv/bin:${PATH}" \
    ANONYMIZED_TELEMETRY=False

RUN pip install --no-cache-dir uv==0.13.7

WORKDIR /app
COPY pyproject.toml uv.lock ./
# Incluye el grupo dev: el mismo contenedor sirve de arnés (pytest).
RUN uv sync --frozen --no-install-project

COPY app ./app
COPY data ./data
COPY tests ./tests
COPY scripts ./scripts

RUN useradd --create-home --uid 10001 lab \
    && mkdir -p /data /app/attacks /app/results \
    && chown -R lab:lab /data /app/attacks /app/results
USER lab

EXPOSE 8000
CMD ["uvicorn", "--factory", "app.main:app_from_env", "--host", "0.0.0.0", "--port", "8000"]
