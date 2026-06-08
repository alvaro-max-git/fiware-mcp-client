FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    FIWARE_CLIENT_CONFIG=/app/config.docker.yaml

WORKDIR /app

COPY pyproject.toml README.md LICENSE ./
COPY app ./app
COPY benchmark ./benchmark
COPY data ./data
COPY fiware-mcp-server ./fiware-mcp-server
COPY prompts ./prompts
COPY config.docker.yaml ./

RUN python -m pip install --upgrade pip \
    && python -m pip install . \
    && mkdir -p /app/data /app/logs

EXPOSE 8000 7860

CMD ["python", "-m", "uvicorn", "app.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
