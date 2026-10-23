# File storage: setup and operations

This project accepts file uploads of these types: image/*, application/pdf, text/csv, up to
**10 MB** each. Every file is checked, scanned for malware **before** it is stored, kept in
an S3-compatible bucket (MinIO API), and every action on it is written to an append-only audit trail.
`docs/storage-security.md` is the threat model. This page is how to run it.

> Design intent for security reviews, not a compliance opinion. Whether a setup satisfies GDPR, SOC 2, ISO 27001,
> HIPAA or PCI DSS depends on how you operate it. What it does and does not cover is listed at the end.

## 1. The pieces

| Piece | What it is | Where it runs |
|---|---|---|
| API | this project, routes under `/files` | your usual place |
| Malware scanner | ClamAV `clamd` (clamav/clamav:1.5.4) | `clamav` service in `docker-compose.yml`; **private network only** (clamd has no authentication or encryption) |
| Object store | the bucket `team-files` | your S3-compatible server (the compose file starts a local one for development) |
| Database | `stor_files` (metadata), `stor_audit_log` (append-only) | the project's PostgreSQL |
| Maintenance | `python -m app.storage.maintenance` | cron / scheduler, see section 6 |

An upload goes: sign-in and role check → rate limit → size and SHA-256 → file type from the bytes → quota →
**malware scan** → pending row → bucket → row becomes `clean` + audit row. If the scanner or the bucket is down
the upload is refused (503); a file is never stored unscanned and never assumed clean.

## 2. Environment

Secrets are environment variables (or `NAME_FILE` pointing at a Docker/Kubernetes secret file). They are never in the
spec, the zip or the builder.

| Variable | Meaning |
|---|---|
| `STORAGE_ENDPOINT_URL` | S3 API address. Empty = AWS. **Required** for this project. Must be `https://` when `APP_ENV=production`. |
| `STORAGE_PUBLIC_ENDPOINT_URL` | Address browsers use in presigned links, if it differs from the one above. |
| `STORAGE_REGION` | Overrides the region in the spec (us-east-1). |
| `STORAGE_ACCESS_KEY_ID`, `STORAGE_SECRET_ACCESS_KEY` | Bucket credentials. On AWS prefer an IAM role (leave both unset). Set both or neither. |
| `STORAGE_SSE` | `auto` (default: SSE-S3 on AWS, nothing on a custom endpoint), `AES256`, `aws:kms` (+ `STORAGE_KMS_KEY_ID`), `none`. |
| `STORAGE_ADDRESSING` | `auto` (path style on a custom endpoint), `path`, `virtual`. |
| `STORAGE_CREATE_BUCKET` | `true` creates a missing bucket at start. Development only; refused in production. |
| `STORAGE_TRUSTED_PROXIES` | Reverse proxies whose `X-Forwarded-For` is believed (default 0). Used for the IP in the audit trail. |
| `CLAMD_HOST`, `CLAMD_PORT` | The scanner (default `clamav:3310`). |
| `STORAGE_SCAN_TIMEOUT_SECONDS` | Longest a scan may take (spec: 120). |
| `APP_ENV` | `production` turns on the strict checks above. |

## 3. Set up the bucket

Create the bucket `team-files` on your S3-compatible server and a credential that may read, write and delete objects under
`teams/files/` in it (the AWS policy in `deploy/storage/iam-policy.json` shows the exact actions; translate it to your
server's policy language). Then:

- Serve the endpoint over **TLS** and set `STORAGE_ENDPOINT_URL=https://...` (production refuses plain http).
- Keep the bucket private (no anonymous access), turn on **server-side encryption** and **versioning** if the server supports them
  (`STORAGE_SSE`), and apply the equivalent of `deploy/storage/lifecycle.json` (expire old versions after 1 day).
- Set `STORAGE_ADDRESSING=path` unless your server is configured for virtual-hosted style.

**About MinIO.** The community edition of MinIO stopped publishing container images in October 2025 and its repository was
archived, so there is no maintained upstream image to pin. This project only uses the S3 API, so a MinIO you already run (or
build and patch yourself) works, and so does any compatible server (SeaweedFS, Ceph RGW, Garage...). The generated
`docker-compose.yml` starts **SeaweedFS** (chrislusf/seaweedfs:4.48) as the local stand-in. It is configured for development:
single node, no replication, plain http on the internal network. Plan real storage before you hold real data.

## 4. The malware scanner

`docker-compose.yml` runs ClamAV with limits derived from this project: files up to **10 MB** are accepted, so clamd
is set to `StreamMaxLength 26M`, and `AlertExceedsMax yes` turns "too large or too deeply nested to scan" into a
detection instead of a silent pass. The signature database lives in the `clamav_db` volume and is refreshed by `freshclam`
inside the container; the first start downloads it (a few minutes, about 1.5 GB of memory when running).

Running clamd elsewhere (Kubernetes, a VM)? Use the same options:

```
StreamMaxLength 26M
MaxFileSize 26M
MaxScanSize 104M
MaxRecursion 10
MaxFiles 10000
AlertExceedsMax yes
```

and allow connections to its port (3310) **only** from the API and the maintenance job. Anyone who can reach clamd can use it; there is
no password to set.

What a scan does not do: it does not catch what no signature knows yet. That is why `--rescan` exists (section 6), why files are served as
attachments with a locked-down content type, and why you should still treat uploaded files as untrusted wherever you open them.

## 5. Roles and access

- `upload`: member, contributor, admin
- `share`: nobody (not granted)
- `read`: viewer, member, contributor, admin
- `read_all`: admin
- `delete`: nobody (not granted)
- `delete_all`: admin
- `operate`: admin

`upload` stores files; `share` may mark a file as readable by every `read` role; `read` downloads own and shared files; `read_all` downloads every file
of the tenant; `delete` removes own files, `delete_all` any; `operate` sees audit trails and scanner health, and quarantines or releases files.
A file you may not see answers exactly like one that does not exist (404).

## 6. Operations

Run the maintenance command at least hourly (it is idempotent, safe to run from several places, and takes row locks with `SKIP LOCKED`):

```bash
docker compose run --rm --no-deps api python -m app.storage.maintenance          # clean up, finish deletes, log the audit digest
docker compose run --rm --no-deps api python -m app.storage.maintenance --rescan # rescan files scanned more than 30 days ago
```

- **Digest.** It logs `storage_audit_digest` with a SHA-256 over yesterday's audit hashes. Copy that line somewhere you control (a log service, a ticket).
  It is what lets you prove later that the trail was not rewritten, even by someone with database superuser rights.
- **Rescan.** Anything that no longer scans clean, or whose bytes no longer match the hash recorded at upload, is quarantined and audited.
- **Alerts worth setting** (log lines, JSON): `storage_scanner_unavailable`, `storage_backend_error`, `storage_rescan_quarantined`, `storage_integrity_mismatch`, and a rise in
  audit events `upload.rejected` with reason `malware_detected`.
- **Health.** `GET /files/status` (operate role) reports scanner and bucket reachability.
- **Quarantine a file:** `POST /files/{id}/quarantine`; **release:** `POST /files/{id}/release` (refused unless the stored bytes still match their hash and scan clean now).

### Erasure requests (GDPR Art. 17 and similar)

`DELETE /files/{id}` removes the object (and old versions where the credentials allow listing them) and blanks the stored file name. A tombstone stays
(id, SHA-256, size, dates) and the audit trail keeps ids and hashes, because records of processing must outlive the data. A file that a record still uses cannot be
deleted (409): remove it from the record first. Backups of the database or bucket are outside this API; keep their retention in line with your policy.

### Audit retention

The audit trail is kept 2555 days (spec; at least 365). The database refuses to delete younger rows, whoever asks. After that, delete in
the maintenance window with `python -m app.storage.maintenance --purge-audit --yes`. The audit trail stores user ids, IP addresses, file ids, hashes, sizes and types. It never stores file content or file names.
IP addresses are personal data in many jurisdictions: they are on because the spec says so (`audit_ip`); turn that off if you do not need them.

### Secret rotation

Create the new credential, deploy it (`STORAGE_ACCESS_KEY_ID` / `STORAGE_SECRET_ACCESS_KEY`, or `*_FILE`), then disable the old one. Nothing else changes.

### Backup and restore

Back up the database (metadata and audit trail) and enable versioning/replication on the bucket. After a restore, run the maintenance command: rows whose object is gone are
found by `--rescan` (`missing` verdict, quarantined).

## 7. Performance and sizing

An upload is read once to hash it, once to scan it and once to store it, so it needs temporary disk equal to the file (`/tmp` of the API container; with the
read-only options of `docker-compose` add a `tmpfs` of at least `10M` per concurrent upload). A scan of a 10 MB file takes seconds on a warm clamd. Rough guide: size clamd for
about 1.5 GB RAM and one CPU per ~5 concurrent scans; the API holds an upload's worker slot while it scans, so raise `UVICORN_WORKERS` rather than the timeout if uploads queue.
These are estimates, not measurements of your hardware.

## 8. What this covers and what it does not

Covered by the design (and tested, see `tests/test_storage_*.py`): size and type checks from the bytes, malware scan before storage with fail-closed behaviour, server-generated keys and
sanitised names, role- and tenant-based access with deny-by-default, attachment-only serving with `nosniff` and a sandbox CSP, per-user rate limit and quota, an append-only hash-chained audit trail,
credentials only from the environment, TLS-only endpoints in production, erasure with tombstones, periodic rescans.

Not covered: signature-less malware, content-aware checks (macros inside documents are not removed; add content disarm and reconstruction if you must open files in office suites), per-object
legal hold or WORM retention (enable S3 Object Lock yourself if a regulation needs it), antivirus for files that were in the bucket before this module, and anything about how you run the servers.
The builder's end-to-end test ran this code against a real ClamAV and a real S3-compatible server (SeaweedFS); AWS S3 itself was not available to it, so run the generated tests and your own acceptance test against your bucket before go-live.
