"""Workflows (generated from the spec: change it in the builder).

Plain data."""

RUNTIME = 'postgres'

MULTI_TENANT = True

CONCURRENCY = 2

WORKFLOWS = {'order_flow': {'on_failure': 'compensate',
                'roles': ['admin', 'manager'],
                'steps': [{'compensate': True,
                           'job': None,
                           'kind': 'hook',
                           'name': 'reserve_stock',
                           'retry': {'backoff': 'exponential',
                                     'backoff_seconds': 5,
                                     'max_attempts': 3},
                           'timeout_seconds': 30},
                          {'compensate': True,
                           'job': None,
                           'kind': 'hook',
                           'name': 'charge_card',
                           'retry': {'backoff': 'exponential',
                                     'backoff_seconds': 5,
                                     'max_attempts': 3},
                           'timeout_seconds': 60},
                          {'compensate': False,
                           'job': None,
                           'kind': 'hook',
                           'name': 'send_receipt',
                           'retry': {'backoff': 'exponential',
                                     'backoff_seconds': 5,
                                     'max_attempts': 3},
                           'timeout_seconds': 30}],
                'timeout_seconds': 3600},
 'receipt_flow': {'on_failure': 'fail',
                  'roles': ['admin'],
                  'steps': [{'compensate': False,
                             'job': None,
                             'kind': 'hook',
                             'name': 'prepare',
                             'retry': {'backoff': 'exponential',
                                       'backoff_seconds': 5,
                                       'max_attempts': 3},
                             'timeout_seconds': 30},
                            {'compensate': False,
                             'job': 'send_receipt_email',
                             'kind': 'job',
                             'name': 'email',
                             'retry': {'backoff': 'exponential',
                                       'backoff_seconds': 5,
                                       'max_attempts': 3},
                             'timeout_seconds': 30}],
                  'timeout_seconds': 600}}
