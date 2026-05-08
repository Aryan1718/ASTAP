FROM docker:29.2.0-cli AS docker_cli

FROM python:3.12-slim

WORKDIR /app

COPY --from=docker_cli /usr/local/bin/docker /usr/local/bin/docker

COPY executor/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt pytest

COPY executor/app /app/executor/app

ENV PYTHONPATH=/app

CMD ["uvicorn", "executor.app.main:app", "--host", "0.0.0.0", "--port", "8080"]
