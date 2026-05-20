FROM python:3.11-slim
WORKDIR /app

# mora02_core library (shared with other apps). Installed before app code
# so Docker layer cache stays warm on app-only changes.
COPY lib/mora02_core /tmp/mora02_core
RUN pip install --no-cache-dir /tmp/mora02_core

# App dependencies + code
COPY apps/pilot/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY apps/pilot/*.py .

EXPOSE 8098
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8098"]
