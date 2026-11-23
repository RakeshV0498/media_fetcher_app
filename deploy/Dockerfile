FROM node:22-slim AS ui
WORKDIR /ui
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
WORKDIR /app/backend
COPY backend/pyproject.toml ./
COPY backend/app ./app
COPY backend/alembic.ini ./
COPY backend/alembic ./alembic
# Install only the declared dependencies; the app runs from source so alembic.ini/alembic sit next to app/.
RUN python -c "import tomllib; print(chr(10).join(tomllib.load(open('pyproject.toml','rb'))['project']['dependencies']))" > /tmp/req.txt \
 && pip install --no-cache-dir -r /tmp/req.txt
ENV PYTHONPATH=/app/backend
COPY --from=ui /ui/dist /app/frontend/dist
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
