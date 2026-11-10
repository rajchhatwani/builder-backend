"""Importable fields per entity (generated from the spec): the columns a CSV may fill, with their limits."""

from app.imports.csv_import import SpecEntity, SpecField

ENTITIES: dict[str, SpecEntity] = {
    'Author': SpecEntity(
        name='Author',
        fields=(
            SpecField(name='name', type='string', required=True, unique=True, default=None, max_length=80, min_value=None, max_value=None, enum_values=None),
            SpecField(name='bio', type='text', required=False, unique=False, default=None, max_length=None, min_value=None, max_value=None, enum_values=None),
            SpecField(name='born_on', type='date', required=False, unique=False, default=None, max_length=None, min_value=None, max_value=None, enum_values=None),
            SpecField(name='rating', type='float', required=False, unique=False, default=None, max_length=None, min_value=0.0, max_value=5.0, enum_values=None),
        ),
    ),
    'Book': SpecEntity(
        name='Book',
        fields=(
            SpecField(name='title', type='string', required=True, unique=False, default=None, max_length=200, min_value=None, max_value=None, enum_values=None),
            SpecField(name='isbn', type='string', required=False, unique=True, default=None, max_length=20, min_value=None, max_value=None, enum_values=None),
            SpecField(name='pages', type='integer', required=True, unique=False, default=100, max_length=None, min_value=1.0, max_value=None, enum_values=None),
            SpecField(name='price', type='decimal', required=False, unique=False, default=9.99, max_length=None, min_value=0.0, max_value=None, enum_values=None),
            SpecField(name='status', type='enum', required=True, unique=False, default='draft', max_length=None, min_value=None, max_value=None, enum_values=('draft', 'published', 'archived')),
            SpecField(name='published_at', type='datetime', required=False, unique=False, default=None, max_length=None, min_value=None, max_value=None, enum_values=None),
            SpecField(name='in_stock', type='boolean', required=True, unique=False, default=True, max_length=None, min_value=None, max_value=None, enum_values=None),
            SpecField(name='extra', type='json', required=False, unique=False, default={'tags': []}, max_length=None, min_value=None, max_value=None, enum_values=None),
            SpecField(name='catalog_id', type='uuid', required=False, unique=False, default=None, max_length=None, min_value=None, max_value=None, enum_values=None),
            SpecField(name='author_id', type='uuid', required=True, unique=False),
            SpecField(name='shelf_id', type='uuid', required=False, unique=False),
        ),
    ),
    'Member': SpecEntity(
        name='Member',
        fields=(
            SpecField(name='name', type='string', required=True, unique=False, default=None, max_length=80, min_value=None, max_value=None, enum_values=None),
            SpecField(name='email', type='string', required=True, unique=True, default=None, max_length=120, min_value=None, max_value=None, enum_values=None),
            SpecField(name='joined_on', type='date', required=False, unique=False, default='2026-01-01', max_length=None, min_value=None, max_value=None, enum_values=None),
            SpecField(name='sponsor_id', type='uuid', required=False, unique=False),
        ),
    ),
    'Profile': SpecEntity(
        name='Profile',
        fields=(
            SpecField(name='bio', type='text', required=True, unique=False, default=None, max_length=None, min_value=None, max_value=None, enum_values=None),
            SpecField(name='member_id', type='uuid', required=True, unique=True),
        ),
    ),
    'Shelf': SpecEntity(
        name='Shelf',
        fields=(
            SpecField(name='label', type='string', required=True, unique=True, default=None, max_length=30, min_value=None, max_value=None, enum_values=None),
        ),
    ),
}
