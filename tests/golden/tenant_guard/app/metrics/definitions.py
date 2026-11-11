"""Metric definitions (generated from the spec: change them in the builder). Plain data."""

from typing import Any

METRICS: dict[str, dict[str, Any]] = {'employee_by_status': {'agg': 'count',
                        'entity': 'Employee',
                        'field': None,
                        'filter': [],
                        'group_by': 'status',
                        'key': 'employee_by_status',
                        'label': 'By status',
                        'unit': None},
 'employee_count': {'agg': 'count',
                    'entity': 'Employee',
                    'field': None,
                    'filter': [],
                    'group_by': None,
                    'key': 'employee_count',
                    'label': 'Employees',
                    'unit': None},
 'salary_total': {'agg': 'sum',
                  'entity': 'Employee',
                  'field': 'salary',
                  'filter': [],
                  'group_by': None,
                  'key': 'salary_total',
                  'label': 'Salary total',
                  'unit': None}}

FIELD_TYPES: dict[str, dict[str, str]] = {'Employee': {'name': 'string', 'notes': 'text', 'salary': 'integer', 'status': 'enum'}}
