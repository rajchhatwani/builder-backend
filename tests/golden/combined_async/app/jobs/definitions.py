"""Jobs, schedules and worker groups (generated from the spec: change it in the builder).

Plain data."""

from typing import Any

JOBS: dict[str, dict[str, Any]] = {'send_invoice': {'handler': 'send_invoice',
                  'queue': 'default',
                  'retry': {'backoff': 'exponential', 'backoff_seconds': 5, 'max_attempts': 4},
                  'timeout_seconds': 60},
 'weekly_dunning': {'handler': 'run_weekly_dunning',
                    'queue': 'reports',
                    'retry': {'backoff': 'fixed', 'backoff_seconds': 60, 'max_attempts': 2},
                    'timeout_seconds': 600}}

SCHEDULES: dict[str, dict[str, Any]] = {'weekly_dunning_monday': {'cron': '0 6 * * 1',
                           'enabled': True,
                           'job': 'weekly_dunning',
                           'missed': 'catch_up_one',
                           'timezone': 'Asia/Kolkata'}}

GROUPS: dict[str, dict[str, Any]] = {'default': {'concurrency': 4, 'placement': 'same_server', 'queues': ['default']},
 'reports': {'concurrency': 2, 'placement': 'separate_server', 'queues': ['reports']}}
