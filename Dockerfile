FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Default to SQLite under /data. In production set DATABASE_URL to a managed
# Postgres (recommended). On Railway, attach a Railway Volume at /data to
# persist SQLite — Docker's VOLUME instruction is unsupported there. The app
# creates this directory on boot, so it also works without a mounted volume.
ENV DATABASE_URL=sqlite:////data/veloxi.db \
    INGEST_ENABLED=false \
    PORT=8000
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import os,urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('PORT','8000')+'/health').status==200 else 1)"

# Serve. The app creates tables on boot (with retry) inside the FastAPI
# lifespan, so the web server always starts and /health stays available even if
# the DB is briefly unreachable. Run `python -m app.cli seed` once after deploy.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
