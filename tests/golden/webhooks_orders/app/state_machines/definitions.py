"""State machines (generated from the spec: change them in the builder).

Plain data. A guard is a type-checked expression tree run by app/state_machines/expr;
nothing in this file is ever evaluated as code."""

MACHINES = {'Order': {'field': 'status',
           'initial': 'draft',
           'states': ['draft', 'submitted', 'approved'],
           'table': 'orders',
           'transitions': [{'auto': False,
                            'from': ['draft'],
                            'guard': None,
                            'name': 'submit',
                            'roles': [],
                            'to': 'submitted',
                            'when': None},
                           {'auto': False,
                            'from': ['submitted'],
                            'guard': None,
                            'name': 'approve',
                            'roles': ['admin', 'manager'],
                            'to': 'approved',
                            'when': None}]}}
