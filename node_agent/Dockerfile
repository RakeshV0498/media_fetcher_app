# Build context = repo root. Reuses backend/app/postprocess + parsing (no DB, no scheduler).
FROM python:3.12-slim
WORKDIR /srv
COPY backend/pyproject.toml ./backend/
COPY backend/app ./backend/app
WORKDIR /srv/backend
RUN python -c "import tomllib; print(chr(10).join(tomllib.load(open('pyproject.toml','rb'))['project']['dependencies']))" > /tmp/req.txt \
 && pip install --no-cache-dir -r /tmp/req.txt
WORKDIR /srv
ENV PYTHONPATH=/srv/backend:/srv
COPY node_agent/agent ./agent
CMD ["uvicorn", "agent.main:app", "--host", "0.0.0.0", "--port", "8800"]
