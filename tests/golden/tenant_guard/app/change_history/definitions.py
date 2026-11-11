"""Change history (generated from the spec: change it in the builder).

Plain data. Only the fields listed here are ever recorded."""

MAX_VALUE_BYTES = 4096

HISTORY = {'Employee': {'fields': ['name', 'notes', 'salary'],
              'path': 'employees',
              'retention_days': 30,
              'table': 'employees',
              'view_roles': ['staff']}}
