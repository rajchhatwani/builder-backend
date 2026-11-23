"""Importable fields per entity (generated from the spec): the columns a CSV may fill, with their limits."""

from app.imports.csv_import import SpecEntity, SpecField

ENTITIES: dict[str, SpecEntity] = {
    'Product': SpecEntity(
        name='Product',
        fields=(
            SpecField(name='title', type='string', required=True, unique=False, default=None, max_length=120, min_value=None, max_value=None, enum_values=None),
            SpecField(name='price_cents', type='integer', required=True, unique=False, default=None, max_length=None, min_value=None, max_value=None, enum_values=None),
            SpecField(name='internal_cost', type='integer', required=False, unique=False, default=None, max_length=None, min_value=None, max_value=None, enum_values=None),
        ),
    ),
    'Review': SpecEntity(
        name='Review',
        fields=(
            SpecField(name='stars', type='integer', required=True, unique=False, default=None, max_length=None, min_value=None, max_value=None, enum_values=None),
            SpecField(name='body', type='string', required=False, unique=False, default=None, max_length=300, min_value=None, max_value=None, enum_values=None),
        ),
    ),
}
