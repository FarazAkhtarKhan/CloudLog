# CloudLog offline demo: emulated AWS stack + dashboard in one container.
#   docker build -t cloudlog .
#   docker run --rm -p 8000:8000 cloudlog          -> http://localhost:8000

# Stage 1: build the React dashboard
FROM docker.io/library/node:22-alpine AS dashboard
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# Stage 2: Python runtime with the backend and the built dashboard
FROM docker.io/library/python:3.11-slim
WORKDIR /app
RUN pip install --no-cache-dir "boto3>=1.34" "moto[s3,dynamodb,sns]>=5.0" \
 && useradd --create-home --uid 10001 cloudlog
COPY backend/ backend/
COPY --from=dashboard /app/frontend/dist frontend/dist
USER cloudlog
ENV HOST=0.0.0.0 PORT=8000 PYTHONUNBUFFERED=1
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s CMD python -c "import urllib.request,sys; urllib.request.urlopen('http://127.0.0.1:8000/rules', timeout=2)" || exit 1
CMD ["python", "-m", "backend.local.emulator", "--seed", "--traffic", "20"]
