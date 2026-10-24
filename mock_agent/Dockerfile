# Build context is the repo root (docker-compose.yml): the agent reuses pareeksha.gnani and the
# frozen pareeksha-audio-v1 message models from backend/pareeksha.
FROM python:3.12-slim
WORKDIR /app
RUN --mount=type=secret,id=ca,required=false \
    if [ -f /run/secrets/ca ]; then export PIP_CERT=/run/secrets/ca; fi; \
    pip install --no-cache-dir "gnani-vachana>=0.8.2" "websockets>=12.0,<16.0" "pydantic>=2.7" "requests"
COPY backend/pareeksha /app/pareeksha
COPY mock_agent /app/mock_agent
ENV PYTHONPATH=/app PYTHONUNBUFFERED=1 MOCK_AGENT_TTS_CACHE=/tmp/mock_agent_tts
EXPOSE 8765
CMD ["python", "-m", "mock_agent.server"]
