FROM python:3.12-slim

WORKDIR /app

RUN useradd --create-home --shell /bin/bash kubeguardian

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY controller/ ./controller/

RUN mkdir -p /var/log/kubeguardian && chown -R kubeguardian:kubeguardian /var/log/kubeguardian

USER kubeguardian

ENV PYTHONUNBUFFERED=1
ENV INCIDENT_LOG_PATH=/var/log/kubeguardian/incidents.jsonl

EXPOSE 8000

CMD ["python", "-m", "controller.main"]
