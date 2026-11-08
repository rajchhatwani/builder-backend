"""Authorization policies (generated from the spec: change them in the builder).

Read once at start-up by app/auth/authorize.py. A malformed entry stops the application
from starting rather than being skipped."""

POLICY_DATA = {'attachments': {'*': ['read_all'], 'admin': ['admin_all'], 'member': ['own_deals']},
 'field_types': {'Customer': {'created_at': 'datetime',
                              'id': 'uuid',
                              'name': 'string',
                              'updated_at': 'datetime'},
                 'Deal': {'created_at': 'datetime',
                          'created_by_id': 'uuid',
                          'id': 'uuid',
                          'title': 'string',
                          'updated_at': 'datetime'}},
 'model': 'pbac',
 'policies': {'admin_all': {'actions': ['*'], 'effect': 'allow', 'when': None},
              'own_deals': {'actions': ['Deal.create', 'Deal.update'],
                            'effect': 'allow',
                            'when': {'left': {'resource': 'created_by_id'},
                                     'op': 'eq',
                                     'right': {'subject': 'id'}}},
              'read_all': {'actions': ['Customer.list',
                                       'Customer.get',
                                       'Deal.list',
                                       'Deal.get'],
                           'effect': 'allow',
                           'when': None}},
 'subject_attributes': ['email', 'id', 'roles', 'tenant_id']}
