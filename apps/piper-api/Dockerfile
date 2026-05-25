FROM python:3.11-slim

RUN apt-get update && \
    apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/*

# Install Piper binary
RUN curl -L https://github.com/rhasspy/piper/releases/download/2023.11.14-2/piper_linux_x86_64.tar.gz \
    | tar xz -C /usr/local

# Python deps
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY piper-api.py /app/piper-api.py
WORKDIR /app

EXPOSE 8107

HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
  CMD curl -f http://localhost:8107/health || exit 1

CMD ["uvicorn", "piper-api:app", "--host", "0.0.0.0", "--port", "8107"]
