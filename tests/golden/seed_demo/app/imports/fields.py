"""Importable fields per entity (generated from the spec): the columns a CSV may fill, with their limits."""

from app.imports.csv_import import SpecEntity, SpecField

ENTITIES: dict[str, SpecEntity] = {
    'Customer': SpecEntity(
        name='Customer',
        fields=(
            SpecField(name='name', type='string', required=True, unique=False, default=None, max_length=80, min_value=None, max_value=None, enum_values=None),
            SpecField(name='email', type='string', required=True, unique=True, default=None, max_length=120, min_value=None, max_value=None, enum_values=None),
            SpecField(name='notes', type='text', required=False, unique=False, default=None, max_length=None, min_value=None, max_value=None, enum_values=None),
            SpecField(name='active', type='boolean', required=False, unique=False, default=True, max_length=None, min_value=None, max_value=None, enum_values=None),
        ),
    ),
    'Invoice': SpecEntity(
        name='Invoice',
        fields=(
            SpecField(name='invoice_no', type='string', required=True, unique=True, default=None, max_length=40, min_value=None, max_value=None, enum_values=None),
            SpecField(name='amount', type='decimal', required=True, unique=False, default=None, max_length=None, min_value=0.0, max_value=None, enum_values=None),
            SpecField(name='issued_on', type='date', required=True, unique=False, default=None, max_length=None, min_value=None, max_value=None, enum_values=None),
            SpecField(name='memo', type='string', required=False, unique=False, default=None, max_length=200, min_value=None, max_value=None, enum_values=None),
            SpecField(name='customer_id', type='uuid', required=True, unique=False),
        ),
    ),
}
