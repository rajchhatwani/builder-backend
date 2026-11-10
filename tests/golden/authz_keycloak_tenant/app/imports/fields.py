"""Importable fields per entity (generated from the spec): the columns a CSV may fill, with their limits."""

from app.imports.csv_import import SpecEntity, SpecField

ENTITIES: dict[str, SpecEntity] = {
    'Customer': SpecEntity(
        name='Customer',
        fields=(
            SpecField(name='name', type='string', required=True, unique=False, default=None, max_length=100, min_value=None, max_value=None, enum_values=None),
        ),
    ),
    'Deal': SpecEntity(
        name='Deal',
        fields=(
            SpecField(name='title', type='string', required=True, unique=False, default=None, max_length=100, min_value=None, max_value=None, enum_values=None),
        ),
    ),
}
