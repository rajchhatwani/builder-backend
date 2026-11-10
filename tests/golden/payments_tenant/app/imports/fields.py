"""Importable fields per entity (generated from the spec): the columns a CSV may fill, with their limits."""

from app.imports.csv_import import SpecEntity, SpecField

ENTITIES: dict[str, SpecEntity] = {
    'Order': SpecEntity(
        name='Order',
        fields=(
            SpecField(name='total', type='decimal', required=True, unique=False, default=None, max_length=None, min_value=0.01, max_value=100000.0, enum_values=None),
            SpecField(name='currency', type='string', required=True, unique=False, default=None, max_length=3, min_value=None, max_value=None, enum_values=None),
            SpecField(name='state', type='enum', required=True, unique=False, default='open', max_length=None, min_value=None, max_value=None, enum_values=('open', 'settled', 'part_refunded', 'refunded')),
        ),
    ),
}
