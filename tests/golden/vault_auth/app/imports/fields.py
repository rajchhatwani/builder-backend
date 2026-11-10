"""Importable fields per entity (generated from the spec): the columns a CSV may fill, with their limits."""

from app.imports.csv_import import SpecEntity, SpecField

ENTITIES: dict[str, SpecEntity] = {
    'Secret': SpecEntity(
        name='Secret',
        fields=(
            SpecField(name='label', type='string', required=True, unique=False, default=None, max_length=80, min_value=None, max_value=None, enum_values=None),
        ),
    ),
}
