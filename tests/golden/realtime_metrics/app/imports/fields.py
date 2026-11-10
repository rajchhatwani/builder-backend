"""Importable fields per entity (generated from the spec): the columns a CSV may fill, with their limits."""

from app.imports.csv_import import SpecEntity, SpecField

ENTITIES: dict[str, SpecEntity] = {
    'Expense': SpecEntity(
        name='Expense',
        fields=(
            SpecField(name='category', type='string', required=True, unique=False, default=None, max_length=40, min_value=None, max_value=None, enum_values=None),
            SpecField(name='amount', type='decimal', required=True, unique=False, default=None, max_length=None, min_value=None, max_value=None, enum_values=None),
            SpecField(name='qty', type='integer', required=False, unique=False, default=None, max_length=None, min_value=None, max_value=None, enum_values=None),
            SpecField(name='rate', type='float', required=False, unique=False, default=None, max_length=None, min_value=None, max_value=None, enum_values=None),
            SpecField(name='paid', type='boolean', required=False, unique=False, default=None, max_length=None, min_value=None, max_value=None, enum_values=None),
            SpecField(name='cost_basis', type='decimal', required=False, unique=False, default=None, max_length=None, min_value=None, max_value=None, enum_values=None),
            SpecField(name='spent_on', type='date', required=False, unique=False, default=None, max_length=None, min_value=None, max_value=None, enum_values=None),
            SpecField(name='logged_at', type='datetime', required=False, unique=False, default=None, max_length=None, min_value=None, max_value=None, enum_values=None),
            SpecField(name='code', type='string', required=False, unique=False, default=None, max_length=20, min_value=None, max_value=None, enum_values=None),
        ),
    ),
    'Payroll': SpecEntity(
        name='Payroll',
        fields=(
            SpecField(name='person', type='string', required=True, unique=False, default=None, max_length=80, min_value=None, max_value=None, enum_values=None),
            SpecField(name='salary', type='decimal', required=True, unique=False, default=None, max_length=None, min_value=None, max_value=None, enum_values=None),
        ),
    ),
}
