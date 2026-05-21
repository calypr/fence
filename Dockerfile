# To build:
#   docker build -t quay.io/<org>/fence:latest .
# To run:
#   docker run -p 80:80 \
#     -v ~/.gen3/fence/fence-config.yaml:/var/www/fence/fence-config.yaml \
#     -v ./keys:/fence/keys \
#     quay.io/<org>/fence:latest

FROM python:3.13-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    VENV_PATH=/opt/venv

WORKDIR /src

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    git \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv "${VENV_PATH}"
ENV PATH="${VENV_PATH}/bin:${PATH}"

RUN pip install --no-cache-dir --upgrade pip setuptools wheel

COPY . /src

RUN pip install --no-cache-dir .
RUN /opt/venv/bin/python -m gunicorn --version >/dev/null

ARG GITCOMMIT=unknown
ARG GITVERSION=unknown
RUN resolved_commit="$GITCOMMIT"; \
    resolved_version="$GITVERSION"; \
    if [ "$resolved_commit" = "unknown" ] && git rev-parse HEAD >/dev/null 2>&1; then \
      resolved_commit="$(git rev-parse HEAD)"; \
    fi; \
    if [ "$resolved_version" = "unknown" ] && git describe --always --tags >/dev/null 2>&1; then \
      resolved_version="$(git describe --always --tags)"; \
    fi; \
    printf 'COMMIT="%s"\nVERSION="%s"\n' "$resolved_commit" "$resolved_version" > /src/fence/version_data.py

FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:${PATH}" \
    PROMETHEUS_MULTIPROC_DIR=/var/tmp/prometheus_metrics

WORKDIR /fence

RUN apt-get update && apt-get install -y --no-install-recommends \
    bash \
    ca-certificates \
    ccrypt \
    libpq5 \
    nginx \
    openssh-client \
    tar \
    tzdata \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd --system gen3 && \
    useradd --system --gid gen3 --home-dir /fence --shell /usr/sbin/nologin gen3 && \
    mkdir -p \
      /fence/keys \
      /run/nginx \
      /var/lib/nginx \
      /var/log/nginx \
      /var/tmp/prometheus_metrics \
      /var/www/fence && \
    chown -R gen3:gen3 \
      /fence \
      /run/nginx \
      /var/lib/nginx \
      /var/log/nginx \
      /var/tmp/prometheus_metrics \
      /var/www/fence

COPY --from=builder /opt/venv /opt/venv
COPY --from=builder /src /fence

RUN printf '%s\n' \
    'user gen3;' \
    'worker_processes auto;' \
    'pid /run/nginx.pid;' \
    'events {' \
    '    worker_connections 1024;' \
    '}' \
    'http {' \
    '    include /etc/nginx/mime.types;' \
    '    default_type application/octet-stream;' \
    '    access_log /var/log/nginx/access.log;' \
    '    error_log /var/log/nginx/error.log warn;' \
    '    sendfile on;' \
    '    tcp_nopush on;' \
    '    keepalive_timeout 65;' \
    '    server {' \
    '        listen 80;' \
    '        server_name _;' \
    '        client_max_body_size 64m;' \
    '        location / {' \
    '            proxy_pass http://127.0.0.1:8000;' \
    '            proxy_http_version 1.1;' \
    '            proxy_set_header Host $host;' \
    '            proxy_set_header X-Real-IP $remote_addr;' \
    '            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;' \
    '            proxy_set_header X-Forwarded-Proto $scheme;' \
    '            proxy_set_header Connection "";' \
    '        }' \
    '    }' \
    '}' \
    > /etc/nginx/nginx.conf && \
    ln -sf /dev/stdout /var/log/nginx/access.log && \
    ln -sf /dev/stderr /var/log/nginx/error.log

EXPOSE 80
CMD ["/bin/bash", "/fence/dockerrun.bash"]
