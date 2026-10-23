.PHONY: up down test lint
up:
	docker compose up --build

down:
	docker compose down

# Runs the smoke tests against a throwaway "<db>_test" database, never the dev database.
test:
	# Only the database is needed: the tests sign their own tokens, so Keycloak is not started.
	# The placeholders satisfy the required settings of the services this target does not run.
	docker compose up -d --wait db
	KEYCLOAK_DB_PASSWORD=unused KC_BOOTSTRAP_ADMIN_USERNAME=unused KC_BOOTSTRAP_ADMIN_PASSWORD=unused KC_IDP_CORP_CLIENT_SECRET=unused KC_IDP_GH_CLIENT_SECRET=unused KC_IDP_GOOGLE_CLIENT_SECRET=unused KC_IDP_WORK_CLIENT_SECRET=unused 		docker compose run --rm --no-deps -e DATABASE_URL=postgresql+asyncpg://app:app@db:5432/app_test api sh -c "python -m tests._prepare_db && alembic upgrade head && pytest"

lint:
	ruff check .
