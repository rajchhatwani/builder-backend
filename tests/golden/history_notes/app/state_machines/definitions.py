"""State machines (generated from the spec: change them in the builder).

Plain data. A guard is a type-checked expression tree run by app/state_machines/expr;
nothing in this file is ever evaluated as code."""

MACHINES = {'Ticket': {'field': 'status',
            'initial': 'open',
            'states': ['open', 'in_progress', 'closed'],
            'table': 'tickets',
            'transitions': [{'auto': False,
                             'from': ['open'],
                             'guard': None,
                             'name': 'start',
                             'roles': ['admin', 'agent'],
                             'to': 'in_progress',
                             'when': None},
                            {'auto': False,
                             'from': ['in_progress'],
                             'guard': None,
                             'name': 'close',
                             'roles': ['admin', 'agent'],
                             'to': 'closed',
                             'when': None}]}}
