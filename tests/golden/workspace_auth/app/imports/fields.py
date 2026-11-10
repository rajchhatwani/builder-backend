"""Importable fields per entity (generated from the spec): the columns a CSV may fill, with their limits."""

from app.imports.csv_import import SpecEntity, SpecField

ENTITIES: dict[str, SpecEntity] = {
    'Announcement': SpecEntity(
        name='Announcement',
        fields=(
            SpecField(name='title', type='string', required=True, unique=False, default=None, max_length=120, min_value=None, max_value=None, enum_values=None),
        ),
    ),
    'Label': SpecEntity(
        name='Label',
        fields=(
            SpecField(name='name', type='string', required=True, unique=False, default=None, max_length=60, min_value=None, max_value=None, enum_values=None),
        ),
    ),
    'Task': SpecEntity(
        name='Task',
        fields=(
            SpecField(name='title', type='string', required=True, unique=False, default=None, max_length=120, min_value=None, max_value=None, enum_values=None),
            SpecField(name='done', type='boolean', required=False, unique=False, default=False, max_length=None, min_value=None, max_value=None, enum_values=None),
            SpecField(name='announcement_id', type='uuid', required=False, unique=False),
        ),
    ),
}
