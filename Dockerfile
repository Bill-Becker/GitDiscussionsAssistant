FROM python:3.11-slim

# Install NLR root certs for machines running on NLR's network.
ARG NREL_ROOT_CERT_URL_ROOT=""
RUN set -x && if [ -n "$NREL_ROOT_CERT_URL_ROOT" ]; then \
      apt-get update && apt-get install -y --no-install-recommends curl ca-certificates && \
      curl -fsSLk -o /usr/local/share/ca-certificates/nrel_root.crt "${NREL_ROOT_CERT_URL_ROOT}/nrel_root.pem" && \
      curl -fsSLk -o /usr/local/share/ca-certificates/nrel_xca1.crt "${NREL_ROOT_CERT_URL_ROOT}/nrel_xca1.pem" && \
      update-ca-certificates && \
      rm -rf /var/lib/apt/lists/*; \
    fi
# Extra CA certs (*.crt) in certs/, e.g. NREL/Netskope roots exported from Windows. Empty folder is fine.
COPY certs/ /usr/local/share/ca-certificates/extra/
RUN update-ca-certificates
# requests (SendGrid) reads REQUESTS_CA_BUNDLE; httpx (OpenAI SDK) and pip read SSL_CERT_FILE / PIP_CERT
ENV REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt \
    SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt \
    PIP_CERT=/etc/ssl/certs/ca-certificates.crt

WORKDIR /app
ENV PYTHONUNBUFFERED=1
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py worker.py guidance.py ./
COPY guidance/ ./guidance/
RUN useradd --create-home appuser
USER appuser
EXPOSE 8000
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
