FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    ffmpeg \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# mora02_core library (shared with other apps). Installed before app code
# so Docker layer cache stays warm on app-only changes.
COPY lib/mora02_core /tmp/mora02_core
RUN pip install --no-cache-dir /tmp/mora02_core

# App dependencies + code (build context is repo root, see docker-compose.yml)
COPY apps/script-runner/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY apps/script-runner/app/ ./

# Fonts (JetBrains Mono) for the typer endpoint
COPY apps/script-runner/fonts/ /app/fonts/

# Create data directories
RUN mkdir -p /data/wip /data/final/gifer /data/final/clipper /data/final/typer

# Expose port
EXPOSE 8096

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8096/health || exit 1

# Run uvicorn
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8096"]
