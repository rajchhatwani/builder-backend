"""Importable fields per entity (generated from the spec): the columns a CSV may fill, with their limits."""

from app.imports.csv_import import SpecEntity, SpecField

ENTITIES: dict[str, SpecEntity] = {
    'Note': SpecEntity(
        name='Note',
        fields=(
            SpecField(name='title', type='string', required=True, unique=False, default=None, max_length=120, min_value=None, max_value=None, enum_values=None),
            SpecField(name='body', type='text', required=False, unique=False, default=None, max_length=None, min_value=None, max_value=None, enum_values=None),
            SpecField(name='payload', type='json', required=False, unique=False, default=None, max_length=None, min_value=None, max_value=None, enum_values=None),
            SpecField(name='private_note', type='text', required=False, unique=False, default=None, max_length=None, min_value=None, max_value=None, enum_values=None),
        ),
    ),
    'Ticket': SpecEntity(
        name='Ticket',
        fields=(
            SpecField(name='subject', type='string', required=True, unique=False, default=None, max_length=120, min_value=None, max_value=None, enum_values=None),
            SpecField(name='assignee', type='string', required=False, unique=False, default=None, max_length=80, min_value=None, max_value=None, enum_values=None),
            SpecField(name='internal_memo', type='text', required=False, unique=False, default=None, max_length=None, min_value=None, max_value=None, enum_values=None),
        ),
    ),
}
