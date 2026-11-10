"""Importable fields per entity (generated from the spec): the columns a CSV may fill, with their limits."""

from app.imports.csv_import import SpecEntity, SpecField

ENTITIES: dict[str, SpecEntity] = {
    'Comment': SpecEntity(
        name='Comment',
        fields=(
            SpecField(name='body', type='text', required=True, unique=False, default=None, max_length=None, min_value=None, max_value=None, enum_values=None),
        ),
    ),
    'Document': SpecEntity(
        name='Document',
        fields=(
            SpecField(name='title', type='string', required=True, unique=False, default=None, max_length=120, min_value=None, max_value=None, enum_values=None),
            SpecField(name='status', type='enum', required=True, unique=False, default=None, max_length=None, min_value=None, max_value=None, enum_values=('draft', 'published', 'archived')),
            SpecField(name='pages', type='integer', required=False, unique=False, default=None, max_length=None, min_value=None, max_value=None, enum_values=None),
        ),
    ),
}
