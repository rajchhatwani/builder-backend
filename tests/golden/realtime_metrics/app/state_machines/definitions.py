"""State machines (generated from the spec: change them in the builder).

Plain data. A guard is a type-checked expression tree run by app/state_machines/expr;
nothing in this file is ever evaluated as code."""

MACHINES = {'Expense': {'field': 'status',
             'initial': 'draft',
             'states': ['draft', 'approved'],
             'table': 'expenses',
             'transitions': [{'auto': False,
                              'from': ['draft'],
                              'guard': None,
                              'name': 'approve',
                              'roles': [],
                              'to': 'approved',
                              'when': None}]}}
