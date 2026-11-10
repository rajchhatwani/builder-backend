"""Importable fields per entity (generated from the spec): the columns a CSV may fill, with their limits."""

from app.imports.csv_import import SpecEntity, SpecField

ENTITIES: dict[str, SpecEntity] = {
    'Employee': SpecEntity(
        name='Employee',
        fields=(
            SpecField(name='name', type='string', required=True, unique=False, default=None, max_length=80, min_value=None, max_value=None, enum_values=None),
            SpecField(name='email', type='string', required=True, unique=True, default=None, max_length=120, min_value=None, max_value=None, enum_values=None),
            SpecField(name='department', type='string', required=False, unique=False, default=None, max_length=60, min_value=None, max_value=None, enum_values=None),
            SpecField(name='leave_balance', type='integer', required=True, unique=False, default=None, max_length=None, min_value=0.0, max_value=None, enum_values=None),
        ),
    ),
    'LeaveRequest': SpecEntity(
        name='LeaveRequest',
        fields=(
            SpecField(name='start_date', type='date', required=True, unique=False, default=None, max_length=None, min_value=None, max_value=None, enum_values=None),
            SpecField(name='end_date', type='date', required=True, unique=False, default=None, max_length=None, min_value=None, max_value=None, enum_values=None),
            SpecField(name='days', type='integer', required=True, unique=False, default=None, max_length=None, min_value=1.0, max_value=60.0, enum_values=None),
            SpecField(name='balance', type='integer', required=True, unique=False, default=None, max_length=None, min_value=0.0, max_value=None, enum_values=None),
            SpecField(name='reason', type='string', required=False, unique=False, default=None, max_length=200, min_value=None, max_value=None, enum_values=None),
            SpecField(name='employee_id', type='uuid', required=True, unique=False),
        ),
    ),
}
