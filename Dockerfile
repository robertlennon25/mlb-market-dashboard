FROM python:3.12-slim

WORKDIR /app

# Install dependencies first (layer cache)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Railway mounts the persistent volume at /data — create it so local runs also work
RUN mkdir -p /data

# Railway injects $PORT at runtime; default to 8000 for local Docker runs
EXPOSE 8000

CMD uvicorn server:app --host 0.0.0.0 --port ${PORT:-8000}
