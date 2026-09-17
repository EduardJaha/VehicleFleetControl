FROM python:3.12-slim-bookworm AS builder
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /build
COPY requirements.txt .
RUN python -m venv /opt/venv && /opt/venv/bin/pip install -r requirements.txt

FROM python:3.12-slim-bookworm AS runtime
ENV PATH=/opt/venv/bin:$PATH PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN groupadd --gid 10001 fleet && useradd --uid 10001 --gid fleet --no-create-home fleet
WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
COPY --chown=fleet:fleet app ./app
COPY --chown=fleet:fleet alembic ./alembic
COPY alembic.ini gunicorn.conf.py ./
RUN mkdir -p /app/uploads /app/data && chown fleet:fleet /app/uploads /app/data
USER 10001:10001
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/ready', timeout=8)"]
CMD ["gunicorn", "app.main:app", "--config", "gunicorn.conf.py"]
