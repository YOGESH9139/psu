FROM python:3.11-slim

WORKDIR /app

# System deps: curl for healthcheck, libmagic for MIME detection, build-essential for C extensions
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    libmagic1 \
    build-essential \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

COPY backend/ .
COPY infra/ /app/infra/

# Run Alembic migrations then start Uvicorn
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1"]
