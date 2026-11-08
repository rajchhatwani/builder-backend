# Runtime image for previews (B3-10). Holds the dependencies of generated projects so that the
# sandbox, which has no network and never pulls, can run them from a read-only code mount.
# Build on the runner:  docker build -t bb-preview-app:1 docker/preview-app
# Extend requirements.txt (curated set, B3-9 dependency policy) before previewing projects that
# use optional features (storage, documents, otel, redis ...).
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
COPY requirements.txt /tmp/requirements.txt
RUN pip install -r /tmp/requirements.txt && rm /tmp/requirements.txt
RUN useradd --system --no-create-home --uid 10001 app
USER 10001
WORKDIR /workspace
