"""Jobs, schedules and worker groups (generated from the spec: change it in the builder).

Plain data."""

from typing import Any

JOBS: dict[str, dict[str, Any]] = {'send_invoice': {'handler': 'send_invoice',
                  'queue': 'default',
                  'retry': {'backoff': 'exponential', 'backoff_seconds': 5, 'max_attempts': 4},
                  'timeout_seconds': 60},
 'webhook_delivery': {'handler': 'webhook_delivery',
                      'queue': 'default',
                      'retry': {'backoff': 'fixed', 'backoff_seconds': 1, 'max_attempts': 4},
                      'timeout_seconds': 60}}

SCHEDULES: dict[str, dict[str, Any]] = {'nightly_invoices': {'cron': '0 2 * * *',
                      'enabled': True,
                      'job': 'send_invoice',
                      'missed': 'skip',
                      'timezone': 'UTC'}}

GROUPS: dict[str, dict[str, Any]] = {'default': {'concurrency': 4, 'placement': 'same_server', 'queues': ['default']}}
