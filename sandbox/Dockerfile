FROM python:3.11-slim

# Minimal test runner only. No network clients, no shell utilities beyond base.
RUN pip install --no-cache-dir pytest==8.3.3

# Unprivileged user — the sandbox never needs root.
RUN useradd --create-home --uid 10001 sandboxer

COPY runner.py /opt/sandbox/runner.py

# Own the queue mount point so the (unprivileged) runner can write results into
# the shared volume Docker initialises from this path.
RUN mkdir -p /sandbox_queue/jobs && chown -R sandboxer:sandboxer /sandbox_queue

ENV SANDBOX_QUEUE_DIR=/sandbox_queue \
    SANDBOX_MAX_TIMEOUT=60 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

USER sandboxer
WORKDIR /workspace

CMD ["python", "/opt/sandbox/runner.py"]
