"""PDF templates (generated from the spec: change them in the builder).

Plain data read by app/documents/router.py; the engine never evaluates anything in it
except the placeholders documented in docs/DOCUMENTS.md."""

TEMPLATES = {'employee_card': {'compute': None,
                   'entity': 'Employee',
                   'id': 'employee_card',
                   'kind': 'custom',
                   'roles': ['staff'],
                   'template': {'blocks': [{'text': 'Employee', 'type': 'heading'},
                                           {'rows': [{'label': 'Name',
                                                      'value': '{{row.name}}'},
                                                     {'label': 'Salary',
                                                      'value': '{{row.salary}}'},
                                                     {'label': 'Notes',
                                                      'value': '{{row.notes}}'}],
                                            'type': 'kv'}],
                                'page': {'margin_mm': 18,
                                         'orientation': 'portrait',
                                         'size': 'A4'},
                                'title': 'Card {{row.name}}'},
                   'title': 'Employee card'}}
