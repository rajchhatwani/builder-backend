"""Change history (generated from the spec: change it in the builder).

Plain data. Only the fields listed here are ever recorded."""

MAX_VALUE_BYTES = 4096

HISTORY = {'Note': {'fields': ['body', 'payload', 'title'],
          'path': 'notes',
          'retention_days': 90,
          'table': 'notes',
          'view_roles': ['admin', 'auditor']},
 'Ticket': {'fields': ['assignee', 'subject'],
            'path': 'tickets',
            'retention_days': 30,
            'table': 'tickets',
            'view_roles': ['admin']}}
