FROM python:3.12-slim

LABEL maintainer="KAS DDNS Updater"
LABEL description="Dynamic DNS updater for ALL-INKL KAS API"

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY ddns_updater.py .

EXPOSE 8000

# Run as non-root
RUN useradd -r -s /bin/false ddns && mkdir -p /data && chown ddns /data
USER ddns

CMD ["python", "-u", "ddns_updater.py"]
