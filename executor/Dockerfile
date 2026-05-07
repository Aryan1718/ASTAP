FROM python:3.12-slim

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends docker.io \
    && rm -rf /var/lib/apt/lists/*

COPY executor/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

COPY executor/app /app/executor/app

ENV PYTHONPATH=/app

CMD ["uvicorn", "executor.app.main:app", "--host", "0.0.0.0", "--port", "8080"]
