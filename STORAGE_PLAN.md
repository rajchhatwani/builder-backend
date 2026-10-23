# File storage option: design and implementation plan

Status legend: `[ ]` todo, `[~]` in progress, `[x]` done. **Update this file as you work** so a new chat can
resume from it. Read also `PAYMENTS_PLAN.md` (the pattern this copies), `KEYCLOAK_PLAN.md`, `PLAN.md`.

## 1. Goal

A project can add **file uploads**: any file type, stored in an S3-compatible bucket, with every file scanned
for malware (ClamAV) **before** it is stored, role-based access, a tamper-evident audit trail and a `file`
field type that entities can use (`Product.image`). Built for security / compliance reviews: nothing is
trusted from the client, nothing is stored unscanned, everything fails closed, no secret in the zip.

## 2. Decisions (agreed with the user 2026-10-24)

- Libraries may be added after research (below). Backend is **S3 or MinIO**, chosen per project. Local disk is not offered.
- "Any file type" is the default; an optional allowlist restricts it. Hardening applies either way.
- **Virus scanning is mandatory and cannot be switched off.** Whole feature in one go, nothing deferred.

Assumed (veto any):
1. `minio` means "a self-hosted S3-compatible server reached at `STORAGE_ENDPOINT_URL`". **Upstream MinIO stopped
   publishing community images in Oct 2025 and archived the repo** (verified: no `minio/minio` or
   `quay.io/minio/minio` tag resolves). The generated app speaks plain S3 (SigV4), so a MinIO you already run, or
   any compatible server, works. The generated *dev* compose ships a different compatible server (section 6).
2. Synchronous scan: upload -> temp file -> sniff -> scan -> put to bucket. An infected or unscanned file never
   reaches the bucket. Scanner down = upload refused (503), never skipped.
3. Downloads default to proxying through the API (full control of headers); `presigned` mode redirects to a
   60-second SigV4 URL instead (the object store must be reachable by the client).
4. Files are private to the uploader; `read_all` roles see every file of the tenant; a file marked `shared`
   (needs the `share` role) is readable by every role in `read`.
5. Audit retention floor 365 days (PCI DSS 10.5 minimum), default 2555 (7 years), configurable up.

## 3. Research summary (what drove the design)

- **OWASP File Upload cheat sheet**: server-generated names, size limit, check actual type not `Content-Type`,
  allowlist over blocklist, AV scan, store away from the web root, authenticate/authorize, rate limit, serve safely.
- **python-multipart** CVEs: CVE-2024-24762 (ReDoS, fixed 0.0.7), CVE-2024-53981 (DoS on line breaks, fixed
  0.0.18), CVE-2026-24486 (path traversal when `UPLOAD_KEEP_FILENAME`, fixed 0.0.22). We pin `>=0.0.22`, never
  use `UPLOAD_DIR`/`KEEP_FILENAME`, and never use client filenames on disk.
- **ClamAV** `clamd` INSTREAM: `zINSTREAM\0`, chunks of 4-byte big-endian length + data, `0` length ends; replies
  `stream: OK` / `stream: <sig> FOUND` / `... ERROR`; total limited by `StreamMaxLength`. The Python clients
  (`pyclamd`, `clamd`) are unmaintained -> we write the ~60-line protocol client with the stdlib (asyncio
  streams) instead of adding a dependency. `AlertExceedsMax yes` turns "too big/too deep to scan" into a detection
  (fail closed). clamd is unauthenticated plain TCP: keep it on a private network only.
- **boto3** (official AWS SDK, actively released). `aioboto3` adds a second dependency chain pinned to botocore
  internals; instead boto3 runs in a thread pool. Recent boto3 sends CRC32 checksums by default which several
  S3-compatible servers reject: we set `request_checksum_calculation="when_required"`. SigV4 + (for custom
  endpoints) path-style addressing; presigned URLs expire <= 300 s.
- **S3 hardening**: Block Public Access, default encryption (SSE-S3 / KMS), TLS-only bucket policy, least-privilege
  IAM (Get/Put/Delete on the prefix only), versioning + lifecycle for noncurrent versions. Shipped as
  `deploy/storage/` files (policy JSON, lifecycle JSON, README commands). The app never creates buckets in production.
- **Compliance** (not legal advice): log who/what/when/where/outcome, log ids and hashes not content or filenames
  (GDPR data minimisation), append-only + hash-chained audit with retention >= 1 year (PCI DSS 10, SOC 2 CC7),
  erasure = delete the object and blank the filename, keep the audit reference (GDPR Art. 17 vs. 30 records).

## 4. Spec (contract builder <-> generator)

```text
Spec.storage: SpecStorage | None            (requires auth.enabled)
SpecStorage
  enabled: bool
  backend: "s3" | "minio"
  bucket: str                               S3 naming rules (3-63, lower case, digits, - .)
  region: str | None                        s3: required; minio: default us-east-1
  key_prefix: str                           default "uploads"; [a-z0-9-/]
  allowed_types: list[str]                  MIME allowlist ("image/png", "image/*"); empty = any
  max_file_mb: int                          1..1024 (default 25)
  user_quota_mb: int | None                 total stored per user, None = unlimited
  uploads_per_hour: int                     per user, 1..10000 (default 60)
  download_mode: "proxy" | "presigned"
  allow_inline_images: bool                 png/jpeg/gif/webp may be shown inline (?inline=1); all else attachment
  roles: { upload, share, read, read_all, delete, delete_all, operate }   empty = nobody (fail closed)
  security: { audit_retention_days >= 365, audit_ip: bool, rescan_after_days 1..365, scan_timeout_seconds 5..600 }
```

Never in the spec or the zip: bucket credentials, endpoint passwords. Env only (`STORAGE_ACCESS_KEY_ID`,
`STORAGE_SECRET_ACCESS_KEY`, `*_FILE` variants; on AWS an instance/task role is preferred and needs neither).

New field type `file`: UUID column (no DB foreign key: entity tables are created before the files table);
checked in the repository on every write (exists, clean, same tenant, uploader or `read_all`/shared);
the file cannot be deleted while a row references it (409 `file_in_use`). Rules: not unique, no default,
the entity's write operations must all be role-restricted.

## 5. Generated project

`app/storage/`: `config.py` (settings, `*_FILE` secrets, production refusals), `sniff.py` (magic-byte type
detection), `names.py` (filename sanitising), `clamav.py` (INSTREAM client), `backend.py` (S3 adapter via boto3,
test hook `set_backend`), `models.py`, `schemas.py`, `service.py`, `audit.py` (hash chain), `limits.py` (ASGI body
cap), `router.py`, `refs.py` (file-field checks + references), `maintenance.py` (CLI: purge stale pending,
retry failed deletes, rescan), migration `0004_storage`, `deploy/storage/*`, tests.

Endpoints: `POST /files` (multipart, one `file` part, optional `shared`), `GET /files`, `GET /files/{id}`,
`GET /files/{id}/download`, `DELETE /files/{id}`, `GET /files/{id}/audit`, `GET /files/status` (operate),
`POST /files/{id}/quarantine`, `POST /files/{id}/release` (operate; release requires a fresh clean scan).

Upload steps (each failure -> one audit row + a stable error code, nothing partial left behind):
auth+role -> rate limit + quota -> body cap (413) -> parse (1 file, <=4 small fields) -> sniff + allowlist (415)
-> SHA-256 + exact size -> pending row -> clamd scan (422 `malware_detected` / 503 `scanner_unavailable`) ->
put to bucket under `prefix/tenant/yyyy/mm/uuid` -> row `clean` + audit, one transaction.
Orphans from a crash are removed by `maintenance`.

Serving: always `Content-Disposition: attachment` (inline only for the 4 image types and only if enabled),
`X-Content-Type-Options: nosniff`, `Content-Security-Policy: default-src 'none'; sandbox`, `Cache-Control:
private, no-store`; type is the *sniffed* type if safe, else `application/octet-stream`. Never the client's.

## 6. Dev compose

`clamav` (pinned `clamav/clamav:1.5.4`, config mounted from `deploy/clamav/clamd.conf`, private network only,
~1.5 GB RAM, downloads signatures on first start). `minio` backend adds an S3-compatible dev server (see the
progress log for the image that was verified). `s3` backend adds nothing: point the env at AWS.

## 7. Phases

- [x] S0 research + this plan
- [x] S1 builder: enums, spec models, validation (`app/core/validation_storage.py`), `file` field type
- [x] S2 builder: table + migration `d4f8b6c21a73`, schemas, service, API, spec round trip
- [x] S3 generator core: config, sniff, names, clamav, backend, models, migration `0004`, audit
- [x] S4 generator: service, router, size-limit middleware, refs / file field, maintenance CLI
- [x] S5 generator: compose (ClamAV + dev S3 server), env, requirements, Makefile, README, `deploy/storage/*`, threat model
- [x] S6 generated tests (~130 per project) + fakes; builder tests; goldens (`storage_s3`, `storage_tenant`, `storage_payments`)
- [x] S7 Docker e2e with real ClamAV and a real S3-compatible server (`tests/e2e/test_storage_stack.py`, 12 tests)
- [x] S8 dashboard: `StoragePanel.tsx`, `file` in the field dialog, overview step, next steps; rendered in a browser
- [x] S9 docs (README, LIMITATIONS), threat model in the zip, honest verified / unverified list below

## 8. Verified / unverified (honest list)

**Verified by automated tests (re-runnable):**
- Builder: 58 validation rules, 14 API tests (switch with impact report, spec round trip, `file` field), generation checks
  (pinned images, dependency floors, migration chain, no secret or real EICAR string in any file, compose parsed as YAML).
- Generated projects `storage_s3`, `storage_tenant` (multi-tenant, allowlist, presigned, inline) and `storage_payments`
  (storage together with payments) migrate, pass `alembic check`, downgrade, pass lint and their own tests on a real PostgreSQL.
- Real stack (`tests/e2e/test_storage_stack.py`): real ClamAV 1.5.4 catches the EICAR test file (plain and inside a zip) and
  nothing reaches the bucket; a 9 MB file goes through S3 multipart upload and comes back identical; the generated S3 adapter
  works against a real server (put, stream, presign, delete); a presigned link works without credentials and a forged one fails;
  stopping the scanner refuses uploads (503) and they recover; a changed object is detected, audited and quarantined; the rescan
  command quarantines a file that is later flagged; delete removes the object; production mode refuses an http endpoint.
- 27 deliberately broken controls (scan skipped, fail-open scanner, allowlist, file names, size caps, tenant filter, role checks,
  file-field check, delete-while-used, headers, audit chain, production checks, secret in repr, rescan hash, ...) are all caught.
- Bugs the real stack found that the in-process tests could not: a missing bucket was reported as a missing object (so the
  status route crashed and the dev bucket was never created); an audit write placed after the last byte of a download was
  cancelled by the server (now detached); my own test data assumed ClamAV flags EICAR inside other text (it does not).

**NOT verified:**
- **AWS S3 itself and a real MinIO.** The real-server run used SeaweedFS; SigV4, multipart, presign and path-style behave the same
  there, but IAM, SSE-KMS, bucket policies and versioning against AWS were never exercised. The shipped policy files are valid JSON
  and follow AWS documentation but were not applied to a bucket.
- Performance and sizing numbers in `STORAGE.md` are estimates; no load test was done.
- Real malware beyond the EICAR test file, and zip bombs beyond ClamAV's own limits (`AlertExceedsMax` is set but untested).
- Kubernetes: no manifests are generated for storage; the ClamAV and bucket guidance is generic.

**Deviations from the first proposal:**
1. Local-disk storage was dropped (you asked for S3 or MinIO).
2. "MinIO" means any S3-compatible server because upstream MinIO no longer publishes images; the dev compose ships SeaweedFS 4.48.
3. ClamAV client written with the standard library instead of adding `pyclamd` / `clamd`.
4. Added: per-user quota and rate limit, `share` role, quarantine / release, scheduled rescan, audit digest, `--purge-audit`.

## 9. Progress log

- 2026-10-24  Research, design, full implementation, real-stack verification, mutation checks and dashboard done in one session.
  Also fixed two pre-existing lint errors in the generated payments tests (unsorted imports, unused `AuthUser` import) that made
  `test_generated_project_passes_ruff` fail before this work.
