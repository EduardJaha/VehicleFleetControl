FROM postgres:17-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends python3 python3-venv age ca-certificates && rm -rf /var/lib/apt/lists/*
COPY backend/requirements.txt /tmp/requirements.txt
RUN python3 -m venv /opt/backup && /opt/backup/bin/pip install --no-cache-dir -r /tmp/requirements.txt
COPY deploy/backup/backup.py /opt/backup.py
ENV PATH=/opt/backup/bin:$PATH PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
USER postgres
ENTRYPOINT ["python", "/opt/backup.py"]
CMD ["schedule"]
