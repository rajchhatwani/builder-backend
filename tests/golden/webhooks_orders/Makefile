.PHONY: up down test lint webhooks-maintenance
up:
	docker compose up --build

down:
	docker compose down

# Runs the smoke tests against a throwaway "<db>_test" database, never the dev database.
test:
	docker compose run --rm -e DATABASE_URL=postgresql+asyncpg://app:app@db:5432/app_test api sh -c "python -m tests._prepare_db && alembic upgrade head && pytest"

lint:
	ruff check .

# Housekeeping for webhooks: deletes old delivery logs (WEBHOOKS_LOG_RETENTION_DAYS, default 30) and old incoming ids.
# Run it daily (cron).
webhooks-maintenance:
	docker compose run --rm api python -m app.webhooks.maintenance
