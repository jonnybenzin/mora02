# Mora02 Knowledge API Container
# Stellt SYNC-Endpoint für System-Assistant bereit

FROM python:3.11-slim

WORKDIR /app

# System-Dependencies + Docker CLI (statisch)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ffmpeg \
    && curl -fsSL https://download.docker.com/linux/static/stable/x86_64/docker-24.0.7.tgz \
    | tar xz --strip-components=1 -C /usr/local/bin docker/docker \
    && rm -rf /var/lib/apt/lists/*

# Python Dependencies
RUN pip install --no-cache-dir \
    flask \
    flask-cors \
    gunicorn \
    requests \
    psycopg2-binary

# API Code kopieren
COPY knowledge-api.py /app/

# Health Check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8095/health || exit 1

# Port
EXPOSE 8095

# Gunicorn für Production (stabiler als Flask dev server)
CMD ["gunicorn", "--bind", "0.0.0.0:8095", "--workers", "1", "--timeout", "120", "knowledge-api:app"]
