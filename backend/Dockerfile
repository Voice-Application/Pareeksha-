FROM python:3.12-slim
WORKDIR /app
# Runtime deps are pinned in requirements.lock, compiled from pyproject.toml [project.dependencies]:
#   uv pip compile backend/pyproject.toml --python-version 3.12 -o backend/requirements.lock
# Optional build secret "ca" = extra CA bundle (only needed behind a TLS-intercepting proxy; see docker-compose.proxy.yml).
COPY requirements.lock /app/requirements.lock
RUN --mount=type=secret,id=ca,required=false \
    if [ -f /run/secrets/ca ]; then export PIP_CERT=/run/secrets/ca; fi; \
    pip install --no-cache-dir -r /app/requirements.lock
COPY . /app
# Install the package itself (deps are layered above) so the pareeksha.connectors entry points
# (webhook, hubspot) are registered in the image.
RUN --mount=type=secret,id=ca,required=false \
    if [ -f /run/secrets/ca ]; then export PIP_CERT=/run/secrets/ca; fi; \
    pip install --no-cache-dir --no-deps /app
ENV PYTHONPATH=/app PYTHONUNBUFFERED=1
