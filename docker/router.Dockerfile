FROM python:3.12-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/app

COPY router/requirements.txt /app/router/requirements.txt
RUN pip install --no-cache-dir -r /app/router/requirements.txt

# The router owns the single management page and imports the check-in adapters
# for manual runs. Provider runtimes remain separate containers and storage.
COPY router /app/router
COPY checkin /app/checkin
RUN mkdir -p /data/checkin

EXPOSE 8080
CMD ["uvicorn", "router.app:app", "--host", "0.0.0.0", "--port", "8080"]
