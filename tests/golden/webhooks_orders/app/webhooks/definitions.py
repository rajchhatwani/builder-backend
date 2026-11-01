"""Webhooks (generated from the spec: change it in the builder).

Plain data. No secret is ever here: signing secrets are in the credential vault."""

ADMIN_ROLE = 'admin'
MULTI_TENANT = True
JOB = 'webhook_delivery'
EVENTS = ('order.created', 'order.transitioned', 'order.updated')
MAX_CONSECUTIVE_FAILURES = 3
SECRET_OVERLAP_HOURS = 24
TIMEOUT_SECONDS = 10.0
MAX_PAYLOAD_BYTES = 262144
ALLOW_HTTP = False
ALLOWED_PORTS = []
INBOUND = {'payments': {'dedupe_days': 7, 'max_body_bytes': 4096, 'tolerance_seconds': 300}}
