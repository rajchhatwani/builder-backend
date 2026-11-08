"""Authorization policies (generated from the spec: change them in the builder).

Read once at start-up by app/auth/authorize.py. A malformed entry stops the application
from starting rather than being skipped."""

POLICY_DATA = {'attachments': {'*': ['own_tickets', 'admins']},
 'field_types': {'Ticket': {'created_at': 'datetime',
                            'created_by_id': 'uuid',
                            'id': 'uuid',
                            'subject': 'string',
                            'updated_at': 'datetime'}},
 'model': 'abac',
 'policies': {'admins': {'actions': ['Ticket.list', 'Ticket.get', 'Ticket.delete'],
                         'effect': 'allow',
                         'when': {'left': {'literal': 'admin'},
                                  'op': 'in',
                                  'right': {'subject': 'roles'}}},
              'own_tickets': {'actions': ['Ticket.*'],
                              'effect': 'allow',
                              'when': {'left': {'resource': 'created_by_id'},
                                       'op': 'eq',
                                       'right': {'subject': 'id'}}}},
 'subject_attributes': ['email', 'id', 'roles']}
