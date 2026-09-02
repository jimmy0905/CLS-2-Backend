FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir httpx==0.28.1 \
    && groupadd --gid 10001 collector \
    && useradd --uid 10001 --gid 10001 --create-home --shell /usr/sbin/nologin collector \
    && mkdir -p /var/lib/n8n-execution-collector \
    && chown collector:collector /var/lib/n8n-execution-collector

COPY --chown=collector:collector infrastructure /app/infrastructure

USER collector:collector

CMD ["python", "-m", "infrastructure.integrations.n8n_execution_collector"]
