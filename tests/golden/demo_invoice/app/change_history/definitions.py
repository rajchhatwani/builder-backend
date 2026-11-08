"""Change history (generated from the spec: change it in the builder).

Plain data. Only the fields listed here are ever recorded."""

MAX_VALUE_BYTES = 4096

HISTORY = {'Invoice': {'fields': ['amount', 'due_date', 'po_amount'],
             'path': 'invoices',
             'retention_days': 365,
             'table': 'invoices',
             'view_roles': ['admin', 'approver']},
 'Supplier': {'fields': ['email', 'name', 'payment_terms'],
              'path': 'suppliers',
              'retention_days': 365,
              'table': 'suppliers',
              'view_roles': ['admin']}}
