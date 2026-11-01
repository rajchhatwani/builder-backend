"""Events (generated from the spec: change it in the builder).

Plain data. Only the fields listed under "fields" are ever published."""

from typing import Any

ADAPTER = 'in_process'
RETENTION_DAYS = 14
MULTI_TENANT = True

ENTITIES: dict[str, dict[str, Any]] = {'Customer': {'event': 'customer',
              'fields': ['id', 'name', 'email', 'created_at', 'updated_at'],
              'machine': False,
              'table': 'customers',
              'tenant': True},
 'Order': {'event': 'order',
           'fields': ['id',
                      'reference',
                      'total',
                      'status',
                      'customer_id',
                      'created_at',
                      'updated_at'],
           'machine': True,
           'table': 'orders',
           'tenant': True}}
