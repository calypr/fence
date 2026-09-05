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
    POETRY_VERSION=2.2.1 \
    POETRY_NO_INTERACTION=1 \
    POETRY_VIRTUALENVS_IN_PROJECT=true

WORKDIR /fence

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    git \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir --upgrade pip setuptools wheel && \
    pip install --no-cache-dir "poetry==${POETRY_VERSION}"

COPY poetry.lock pyproject.toml README.md /fence/
RUN poetry install --no-root --only main

COPY . /fence

RUN poetry install --without dev
RUN /fence/.venv/bin/python -m gunicorn --version >/dev/null

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
    printf 'COMMIT="%s"\nVERSION="%s"\n' "$resolved_commit" "$resolved_version" > /fence/fence/version_data.py

FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/fence/.venv/bin:${PATH}" \
    PROMETHEUS_MULTIPROC_DIR=/var/tmp/prometheus_metrics

WORKDIR /fence

RUN apt-get update && apt-get install -y --no-install-recommends \
    bash \
    ca-certificates \
    ccrypt \
    libpq5 \
    openssh-client \
    openssl \
    tar \
    tzdata \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd --system gen3 && \
    useradd --system --gid gen3 --home-dir /fence --shell /usr/sbin/nologin gen3 && \
    mkdir -p \
      /fence/keys \
      /var/tmp/prometheus_metrics \
      /var/www/fence && \
    chown -R gen3:gen3 \
      /fence \
      /var/tmp/prometheus_metrics \
      /var/www/fence

COPY --from=builder /fence /fence
RUN test "$(head -n 1 /fence/.venv/bin/fence-create)" = '#!/fence/.venv/bin/python'

EXPOSE 80
CMD ["/bin/bash", "/fence/dockerrun.bash"]
