-- Least-privilege database logins for the payments module (generated).
--
-- Three logins instead of one all-powerful one:
--   pay_and_files_migrator  owns the tables and runs migrations. Used only at deploy time.
--   pay_and_files_app       used by the API and the workers. Can read and write data, cannot change
--                      the schema, and can only ever append to the audit log.
--
-- Run it once as the database administrator, with the passwords passed on the command line (never
-- written into this file or committed):
--
--   psql "$ADMIN_DATABASE_URL" \
--        -v migrator_password="$(openssl rand -base64 32)" -v app_password="$(openssl rand -base64 32)" \
--        -v database=pay_and_files -f roles.sql
--
-- Then deploy with DATABASE_URL pointing at the _app login, and give the migration step (the
-- Kubernetes migrate Job, or `alembic upgrade head` run by hand) the _migrator login.
--
-- If the schema already exists (created by another login), hand ownership to the migrator login
-- first:  ALTER TABLE <each table> OWNER TO pay_and_files_migrator;

SELECT format('CREATE ROLE pay_and_files_migrator LOGIN PASSWORD %L', :'migrator_password')
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'pay_and_files_migrator')\gexec
SELECT format('CREATE ROLE pay_and_files_app LOGIN PASSWORD %L', :'app_password')
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'pay_and_files_app')\gexec

GRANT CONNECT ON DATABASE :"database" TO pay_and_files_migrator, pay_and_files_app;
GRANT USAGE ON SCHEMA public TO pay_and_files_app;
GRANT USAGE, CREATE ON SCHEMA public TO pay_and_files_migrator;

-- Tables created from now on by the migrator are usable by the app login automatically.
ALTER DEFAULT PRIVILEGES FOR ROLE pay_and_files_migrator IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO pay_and_files_app;
ALTER DEFAULT PRIVILEGES FOR ROLE pay_and_files_migrator IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO pay_and_files_app;

-- Tables that already exist.
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO pay_and_files_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO pay_and_files_app;

-- The audit trail is append-only for the app, whatever else happens (a trigger enforces this too).
REVOKE UPDATE, DELETE, TRUNCATE ON pay_audit_log FROM pay_and_files_app;
