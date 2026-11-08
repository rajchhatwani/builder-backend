FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /srv

COPY requirements.txt requirements-dev.txt ./
RUN pip install --no-cache-dir -r requirements.txt -r requirements-dev.txt

COPY . .

# The app runs as an unprivileged user, never as root.
RUN useradd --system --no-create-home --uid 10001 app && chown -R app /srv
USER 10001

EXPOSE 8000
# UVICORN_WORKERS: server processes per container (each holds its own database pool).
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers ${UVICORN_WORKERS:-1}"]
