# Purrslogic — Cloud Run (FastAPI + Google ADK + MongoDB MCP via Node)
FROM python:3.13-slim-bookworm

RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Warm npm cache for mongodb-mcp-server (ADK agent spawns via npx)
RUN npx -y mongodb-mcp-server@latest --help >/dev/null 2>&1 || true

COPY app ./app
COPY purrslogic_agent ./purrslogic_agent
COPY static ./static
COPY scripts ./scripts
COPY config/.gitkeep ./config/

ENV PORT=8080
ENV PYTHONUNBUFFERED=1

EXPOSE 8080

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
