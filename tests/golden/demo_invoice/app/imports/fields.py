"""Importable fields per entity (generated from the spec): the columns a CSV may fill, with their limits."""

from app.imports.csv_import import SpecEntity, SpecField

ENTITIES: dict[str, SpecEntity] = {
    'Invoice': SpecEntity(
        name='Invoice',
        fields=(
            SpecField(name='amount', type='decimal', required=True, unique=False, default=None, max_length=None, min_value=0.0, max_value=None, enum_values=None),
            SpecField(name='po_amount', type='decimal', required=True, unique=False, default=None, max_length=None, min_value=0.0, max_value=None, enum_values=None),
            SpecField(name='due_date', type='date', required=False, unique=False, default=None, max_length=None, min_value=None, max_value=None, enum_values=None),
            SpecField(name='memo', type='string', required=False, unique=False, default=None, max_length=200, min_value=None, max_value=None, enum_values=None),
            SpecField(name='supplier_id', type='uuid', required=True, unique=False),
        ),
    ),
    'Supplier': SpecEntity(
        name='Supplier',
        fields=(
            SpecField(name='name', type='string', required=True, unique=False, default=None, max_length=80, min_value=None, max_value=None, enum_values=None),
            SpecField(name='email', type='string', required=True, unique=True, default=None, max_length=120, min_value=None, max_value=None, enum_values=None),
            SpecField(name='payment_terms', type='string', required=False, unique=False, default=None, max_length=40, min_value=None, max_value=None, enum_values=None),
            SpecField(name='active', type='boolean', required=False, unique=False, default=True, max_length=None, min_value=None, max_value=None, enum_values=None),
        ),
    ),
}
