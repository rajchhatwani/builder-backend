"""Importable fields per entity (generated from the spec): the columns a CSV may fill, with their limits."""

from app.imports.csv_import import SpecEntity, SpecField

ENTITIES: dict[str, SpecEntity] = {
    'LeaveRequest': SpecEntity(
        name='LeaveRequest',
        fields=(
            SpecField(name='employee', type='string', required=True, unique=False, default=None, max_length=80, min_value=None, max_value=None, enum_values=None),
            SpecField(name='days', type='integer', required=True, unique=False, default=None, max_length=None, min_value=None, max_value=None, enum_values=None),
            SpecField(name='balance', type='integer', required=True, unique=False, default=None, max_length=None, min_value=None, max_value=None, enum_values=None),
        ),
    ),
}
