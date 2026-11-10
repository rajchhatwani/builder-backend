"""Importable fields per entity (generated from the spec): the columns a CSV may fill, with their limits."""

from app.imports.csv_import import SpecEntity, SpecField

ENTITIES: dict[str, SpecEntity] = {
    'Photo': SpecEntity(
        name='Photo',
        fields=(
            SpecField(name='title', type='string', required=True, unique=False, default=None, max_length=120, min_value=None, max_value=None, enum_values=None),
            SpecField(name='image_id', type='file', required=True, unique=False, default=None, max_length=None, min_value=None, max_value=None, enum_values=None),
            SpecField(name='thumbnail_id', type='file', required=False, unique=False, default=None, max_length=None, min_value=None, max_value=None, enum_values=None),
        ),
    ),
}
