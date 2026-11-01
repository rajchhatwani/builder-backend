"""Jobs, schedules and worker groups (generated from the spec: change it in the builder).

Plain data."""

from typing import Any

JOBS: dict[str, dict[str, Any]] = {'send_receipt_email': {'handler': 'send_receipt_email',
                        'queue': 'default',
                        'retry': {'backoff': 'exponential',
                                  'backoff_seconds': 5,
                                  'max_attempts': 3},
                        'timeout_seconds': 60}}

SCHEDULES: dict[str, dict[str, Any]] = {'weekly_receipts': {'cron': '0 6 * * 1',
                     'enabled': True,
                     'job': 'send_receipt_email',
                     'missed': 'skip',
                     'timezone': 'UTC'}}

GROUPS: dict[str, dict[str, Any]] = {'default': {'concurrency': 2, 'placement': 'same_server', 'queues': ['default']}}
