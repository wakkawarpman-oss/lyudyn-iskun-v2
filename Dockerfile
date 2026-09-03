FROM python:3.11-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends gcc libpq-dev curl && rm -rf /var/lib/apt/lists/*
RUN useradd -m appuser
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN chown -R appuser:appuser /app
EXPOSE 80
# Meaningful only for the web_api service (the only one listening on 80) —
# ai_worker and bot_ui override/disable this in docker-compose.yml since
# they don't serve HTTP and would otherwise show as permanently unhealthy.
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD curl -fsS http://localhost/api/stats || exit 1
USER appuser
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "80"]
