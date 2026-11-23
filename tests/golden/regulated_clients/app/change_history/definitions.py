"""Change history (generated from the spec: change it in the builder).

Plain data. Only the fields listed here are ever recorded."""

MAX_VALUE_BYTES = 4096

HISTORY = {'Order': {'fields': ['reference', 'status'],
           'path': 'orders',
           'retention_days': 30,
           'table': 'orders',
           'view_roles': ['admin']}}
