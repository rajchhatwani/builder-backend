-- Local/dev only (docker compose + test harness). Creates the least-privilege API role so RLS
-- can actually bind it (SEC M-1). The password is a dev placeholder; production uses
-- `BUILDER_APP_DB_PASSWORD=... python -m app.core.rls create-app-role` instead.
DO $$ BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'builder_app') THEN
    CREATE ROLE builder_app LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE NOREPLICATION PASSWORD 'builder_app';
  END IF;
END $$;
GRANT USAGE ON SCHEMA public TO builder_app;
ALTER DEFAULT PRIVILEGES FOR ROLE builder IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO builder_app;
ALTER DEFAULT PRIVILEGES FOR ROLE builder IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO builder_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO builder_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO builder_app;
