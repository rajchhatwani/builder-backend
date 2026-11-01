"""API edge settings (generated from the spec: change them in the builder).

Plain data."""

from typing import Any

IDEMPOTENCY: dict[str, Any] | None = {'max_response_bytes': 65536, 'methods': ['POST'], 'ttl_hours': 24}

RATE_LIMITS: dict[str, Any] | None = {'anonymous': {'capacity': 200, 'refill_per_second': 100.0},
 'groups': [{'cost': 2,
             'methods': ['POST'],
             'name': 'writes',
             'path_prefix': '/orders',
             'tenant': None,
             'user': {'capacity': 500, 'refill_per_second': 50.0}}],
 'read_fail_open': False,
 'tenant': None,
 'user': {'capacity': 1000, 'refill_per_second': 100.0}}

QUOTAS: list[dict[str, Any]] = [{'cost': 1,
  'limit': 1000000,
  'meter': 'order_writes',
  'methods': ['POST'],
  'path_prefix': '/orders',
  'period': 'month'}]

VERSIONING: dict[str, Any] | None = {'default': '2026-11-01',
 'versions': [{'date': '2026-01-15', 'note': 'First public version'},
              {'date': '2026-06-01', 'note': 'Orders: reference replaces ref'},
              {'date': '2026-11-01', 'note': 'Pages: items and total only'}]}

MULTI_TENANT = True
