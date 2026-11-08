"""Change history (generated from the spec: change it in the builder).

Plain data. Only the fields listed here are ever recorded."""

MAX_VALUE_BYTES = 4096

HISTORY = {'Employee': {'fields': ['department', 'leave_balance'],
              'path': 'employees',
              'retention_days': 730,
              'table': 'employees',
              'view_roles': ['hr']},
 'LeaveRequest': {'fields': ['days', 'end_date', 'reason', 'start_date'],
                  'path': 'leave_requests',
                  'retention_days': 730,
                  'table': 'leave_requests',
                  'view_roles': ['hr', 'manager']}}
