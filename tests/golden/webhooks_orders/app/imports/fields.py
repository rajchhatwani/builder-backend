"""Importable fields per entity (generated from the spec): the columns a CSV may fill, with their limits."""

from app.imports.csv_import import SpecEntity, SpecField

ENTITIES: dict[str, SpecEntity] = {
    'Customer': SpecEntity(
        name='Customer',
        fields=(
            SpecField(name='name', type='string', required=True, unique=False, default=None, max_length=120, min_value=None, max_value=None, enum_values=None),
            SpecField(name='email', type='string', required=False, unique=False, default=None, max_length=200, min_value=None, max_value=None, enum_values=None),
            SpecField(name='api_token', type='string', required=False, unique=False, default=None, max_length=100, min_value=None, max_value=None, enum_values=None),
        ),
    ),
    'Order': SpecEntity(
        name='Order',
        fields=(
            SpecField(name='reference', type='string', required=True, unique=False, default=None, max_length=60, min_value=None, max_value=None, enum_values=None),
            SpecField(name='total', type='decimal', required=True, unique=False, default=None, max_length=None, min_value=None, max_value=None, enum_values=None),
            SpecField(name='customer_id', type='uuid', required=False, unique=False),
        ),
    ),
}
