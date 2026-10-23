.PHONY: up down test lint worker reconcile storage-maintenance
up:
	docker compose up --build

down:
	docker compose down

# Runs the smoke tests against a throwaway "<db>_test" database, never the dev database.
test:
	docker compose run --rm -e DATABASE_URL=postgresql+asyncpg://app:app@db:5432/app_test api sh -c "python -m tests._prepare_db && alembic upgrade head && pytest"

lint:
	ruff check .

# Run one more payments worker here (more can run on other machines: deploy/compose.worker.yml).
worker:
	docker compose run --rm payments-worker

# Compare our payments with the provider's and repair differences. Safe to run at any time.
reconcile:
	docker compose run --rm --no-deps payments-worker python -m app.payments.reconcile

# Housekeeping for uploaded files: cleans up after crashes, finishes deletes, logs the audit digest.
# Run it hourly (cron) and with --rescan daily. See deploy/storage/STORAGE.md.
storage-maintenance:
	docker compose run --rm api python -m app.storage.maintenance
