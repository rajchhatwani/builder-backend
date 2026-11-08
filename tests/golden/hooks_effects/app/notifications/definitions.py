"""Notifications (generated from the spec: change it in the builder).

Plain data: types, channels, variables and the DEFAULT templates. A tenant's own templates are in
the database (/notifications/templates)."""

from typing import Any

ADMIN_ROLE = 'admin'
MULTI_TENANT = True
MAX_ATTEMPTS = 3
BACKOFF_SECONDS = 5
RETENTION_DAYS = 30
TYPES: dict[str, Any] = {'order_shipped': {'address_fields': {},
                   'category': 'optional',
                   'channels': ['email', 'sms', 'push'],
                   'default_enabled': True,
                   'on_event': None,
                   'recipient_key_field': None,
                   'templates': {'email': {'body': 'Your order {{ order }} is on its way. '
                                                   'Tracking: {{ tracking }}',
                                           'html': False,
                                           'subject': 'Order {{ order }} shipped'},
                                 'push': {'body': '{{ order }} is on its way',
                                          'html': False,
                                          'subject': 'Order shipped'},
                                 'sms': {'body': 'Order {{ order }} shipped: {{ tracking }}',
                                         'html': False,
                                         'subject': ''}},
                   'variables': ['order', 'tracking']},
 'security_alert': {'address_fields': {},
                    'category': 'transactional',
                    'channels': ['email', 'sms'],
                    'default_enabled': True,
                    'on_event': None,
                    'recipient_key_field': None,
                    'templates': {'email': {'body': 'Security alert: {{ detail }}',
                                            'html': False,
                                            'subject': 'Security alert'},
                                  'sms': {'body': 'Security alert: {{ detail }}',
                                          'html': False,
                                          'subject': ''}},
                    'variables': ['detail']},
 'welcome': {'address_fields': {'email': 'email'},
             'category': 'optional',
             'channels': ['email'],
             'default_enabled': True,
             'on_event': 'customer.created',
             'recipient_key_field': 'id',
             'templates': {'email': {'body': '<p>Hello {{ name }}, welcome aboard.</p>',
                                     'html': True,
                                     'subject': 'Welcome {{ name }}'}},
             'variables': ['name']}}
