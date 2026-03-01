FROM python:3.12-slim

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

COPY worker/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

COPY shared /app/shared
COPY worker/app /app/worker/app

ENV PYTHONPATH=/app

CMD ["rq", "worker", "ingest", "discover", "--url", "redis://queue:6379/0"]
