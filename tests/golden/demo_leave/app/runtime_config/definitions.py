"""Runtime configuration (generated from the spec: change it in the builder).

Plain data; nothing in this file is ever evaluated as code."""

SETTINGS = {'carry_over_days': {'default': 5,
                     'description': None,
                     'edit_roles': ['hr'],
                     'label': 'Days that carry over to the next year',
                     'max_length': None,
                     'maximum': 30,
                     'minimum': 0,
                     'read_roles': ['hr', 'manager'],
                     'type': 'int'},
 'max_days_without_hr': {'default': 5,
                         'description': None,
                         'edit_roles': ['hr'],
                         'label': 'Longest leave a manager may approve alone',
                         'max_length': None,
                         'maximum': 60,
                         'minimum': 1,
                         'read_roles': [],
                         'type': 'int'}}

SEQUENCES = {'request_no': {'padding': 4,
                'per_tenant': False,
                'prefix': 'LR-',
                'reset_yearly': True,
                'start': 1,
                'view_roles': ['hr']}}

LISTS = {'leave_type': {'edit_roles': ['hr'],
                'items': [{'color': '#2563eb',
                           'label': 'Annual leave',
                           'locked': True,
                           'value': 'annual'},
                          {'color': '#dc2626',
                           'label': 'Sick leave',
                           'locked': True,
                           'value': 'sick'},
                          {'color': '#6b7280',
                           'label': 'Unpaid leave',
                           'locked': False,
                           'value': 'unpaid'},
                          {'color': '#16a34a',
                           'label': 'Parental leave',
                           'locked': False,
                           'value': 'parental'}],
                'label': 'Leave types',
                'max_items': 12}}
