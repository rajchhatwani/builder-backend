"""Importable fields per entity (generated from the spec): the columns a CSV may fill, with their limits."""

from app.imports.csv_import import SpecEntity, SpecField

ENTITIES: dict[str, SpecEntity] = {
    'Order': SpecEntity(
        name='Order',
        fields=(
            SpecField(name='total', type='decimal', required=True, unique=False, default=None, max_length=None, min_value=1.0, max_value=100000.0, enum_values=None),
            SpecField(name='status', type='enum', required=True, unique=False, default='pending', max_length=None, min_value=None, max_value=None, enum_values=('pending', 'paid', 'partially_refunded', 'refunded', 'cancelled')),
        ),
    ),
}
