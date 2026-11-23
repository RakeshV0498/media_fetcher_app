# Build context = repo root. Reuses backend/app/postprocess + parsing (no DB, no scheduler).
FROM python:3.12-slim
WORKDIR /srv
COPY backend/pyproject.toml ./backend/
COPY backend/app ./backend/app
RUN pip install --no-cache-dir ./backend
COPY node_agent/agent ./agent
CMD ["uvicorn", "agent.main:app", "--host", "0.0.0.0", "--port", "8800"]
