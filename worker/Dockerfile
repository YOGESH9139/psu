FROM python:3.11-slim

WORKDIR /app

# Tesseract for OCR, Poppler for PDF utilities, libmagic for MIME sniffing.
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    tesseract-ocr-eng \
    poppler-utils \
    libmagic1 \
    curl \
    build-essential \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

COPY worker/requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Pre-stage the embedding model INTO THE IMAGE. Build time is the only moment
# this container is allowed to reach the network; at runtime it is air-gapped.
ENV FASTEMBED_CACHE_PATH=/opt/models/fastembed \
    HF_HOME=/opt/models/hf \
    TRANSFORMERS_OFFLINE=1 \
    HF_HUB_OFFLINE=1
RUN mkdir -p /opt/models && \
    HF_HUB_OFFLINE=0 python -c "\
from fastembed import TextEmbedding; \
list(TextEmbedding(model_name='BAAI/bge-small-en-v1.5').embed(['warm up the on-disk cache'])); \
print('embedding model staged')"

COPY worker /app/worker
COPY backend/app /app/app
COPY infra /app/infra

ENV PYTHONPATH=/app \
    PYTHONUNBUFFERED=1

CMD ["python", "-m", "worker.main"]
