FROM python:3.12-slim
WORKDIR /app
# Minimal runtime deps for INFRA-01; BE-API/INFRA-02 replace this with the pyproject install.
# Optional build secret "ca" = extra CA bundle (only needed behind a TLS-intercepting proxy; see docker-compose.proxy.yml).
RUN --mount=type=secret,id=ca,required=false \
    if [ -f /run/secrets/ca ]; then export PIP_CERT=/run/secrets/ca; fi; \
    pip install --no-cache-dir "fastapi>=0.115" "uvicorn>=0.30" "psycopg[binary]>=3.2" "aiokafka>=0.11" "alembic>=1.13" "sqlalchemy>=2.0" "python-multipart>=0.0.9" "pydantic-settings>=2.3"
COPY . /app
ENV PYTHONPATH=/app PYTHONUNBUFFERED=1
