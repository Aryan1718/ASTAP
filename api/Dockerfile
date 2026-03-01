FROM python:3.12-slim

WORKDIR /app

COPY api/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

COPY shared /app/shared
COPY api/app /app/api/app

ENV PYTHONPATH=/app

CMD ["uvicorn", "api.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
