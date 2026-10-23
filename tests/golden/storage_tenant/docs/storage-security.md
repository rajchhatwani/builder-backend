# File storage: threat model

What can go wrong with file uploads, and what this project does about it. Each row names the test that checks it
(`tests/test_storage_security.py`, `tests/test_storage_upload.py`, `tests/test_storage_sniff.py`) so a reviewer can run it.

Assets: the stored files, the people's accounts, the server and the other systems that open these files, the audit trail.
Attackers considered: an anonymous visitor, a signed-in user of low privilege, a user of another tenant, someone who controls an uploaded file's bytes and name,
and a compromised dependency or network neighbour of the scanner or the bucket. Out of scope: an attacker with database or bucket administrator rights.

| # | Threat | Control | Check |
|---|---|---|---|
| 1 | Malware uploaded and later served to other users | ClamAV scan **before** storage; scanner down = upload refused; `AlertExceedsMax` makes unscannable archives a detection; periodic rescan quarantines what signatures learn later | `test_malware_is_rejected_and_never_stored`, `test_scanner_down_refuses_the_upload`, `test_rescan_quarantines_a_file_that_is_no_longer_clean` |
| 2 | Executable or script renamed to look harmless | Type decided from the bytes, never from `Content-Type` or the extension; allowlist applies to the detected type | `test_renamed_executable_is_not_an_image`, `test_declared_type_is_not_trusted` |
| 3 | Stored XSS through an uploaded HTML/SVG file | Always `Content-Disposition: attachment`, `X-Content-Type-Options: nosniff`, `Content-Security-Policy: default-src 'none'; sandbox`, generic content type unless the file is a plain image and inline is enabled | `test_download_headers_are_safe`, `test_html_and_svg_are_never_served_inline` |
| 4 | Path traversal, overwrite or guessing through the file name | Storage key is built from the configured prefix, tenant id, date and a random UUID; the client's name is only cleaned for display (`names.py`) | `test_filenames_are_sanitised_and_never_decide_the_key`, `test_storage_keys_are_random` |
| 5 | Denial of service by a huge or endless body | Byte-counting middleware refuses the request as it arrives (413), whatever `Content-Length` says; hash/size verified again; per-user rate limit and quota; scan timeout | `test_oversize_body_is_refused_early`, `test_rate_limit`, `test_quota` |
| 6 | Reading or deleting someone else's file | Deny-by-default roles; files not visible to the caller are answered 404; tenant filter on every query; ownership for delete | `test_users_cannot_see_each_others_files`, `test_other_tenant_cannot_see_files`, `test_only_allowed_roles_can_act` |
| 7 | Attaching someone else's file to a record, or deleting a file a record uses | `file` fields are checked on every write (exists, clean, same tenant, own or shared, row locked until commit); delete refuses while referenced | `test_file_field_rejects_foreign_and_missing_files` |
| 8 | Tampering with stored bytes | SHA-256 recorded at upload; verified on every proxied download and on rescan; mismatch is audited and quarantined | `test_tampered_object_is_detected` |
| 9 | Tampering with the audit trail | Append-only table (triggers refuse UPDATE, DELETE before retention, TRUNCATE); per-file hash chain; daily digest to store elsewhere | `test_audit_trail_is_append_only`, `test_audit_chain_detects_tampering` |
| 10 | Leaking secrets or personal data through logs, errors or the audit trail | Credentials only from the environment, `SecretStr`, redaction of log lines and audit data; the audit trail has ids and hashes, never contents or names; storage keys and the bucket never appear in responses; provider error text is never passed through | `test_secrets_never_leak`, `test_responses_hide_storage_internals` |
| 11 | Misconfiguration in production | Start-up refuses plain-http endpoints, half-set credentials, development bucket creation, bad settings | `test_unsafe_settings_are_refused` |
| 12 | Scanner or bucket abused as a network service | clamd listens on a private network only; compose publishes no port for it or the dev S3 server; least-privilege IAM policy provided | (deployment, see `deploy/storage/STORAGE.md`) |
| 13 | A stale or partial upload (crash between scan and store) | `pending` rows and orphaned objects are removed by the maintenance command; deletes that failed are retried | `test_maintenance_cleans_up_after_a_crash` |

## Residual risks (decided, not fixed)

- A file nobody's signatures recognise yet passes the scan. Mitigations: rescans, attachment-only serving, no execution on the server. Opening files in desktop software is your risk to manage.
- Documents with macros are accepted when their type is allowed. Add content disarm and reconstruction if you must open them.
- The audit trail's integrity against a database administrator rests on the daily digest you store elsewhere.
- A presigned download link (when `download_mode` is `presigned`) works for anyone who holds it until it expires (60 seconds) and is not logged by this application when used.
- Rate limits count attempts per user, not per address: a botnet of valid accounts is a registration/abuse problem for the auth module.
