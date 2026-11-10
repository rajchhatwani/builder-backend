"""Importable fields per entity (generated from the spec): the columns a CSV may fill, with their limits."""

from app.imports.csv_import import SpecEntity, SpecField

ENTITIES: dict[str, SpecEntity] = {
    'Contact': SpecEntity(
        name='Contact',
        fields=(
            SpecField(name='full_name', type='string', required=True, unique=False, default=None, max_length=120, min_value=None, max_value=None, enum_values=None),
        ),
    ),
    'Note': SpecEntity(
        name='Note',
        fields=(
            SpecField(name='title', type='string', required=True, unique=False, default=None, max_length=120, min_value=None, max_value=None, enum_values=None),
        ),
    ),
}
