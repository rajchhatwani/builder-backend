"""Importable fields per entity (generated from the spec): the columns a CSV may fill, with their limits."""

from app.imports.csv_import import SpecEntity, SpecField

ENTITIES: dict[str, SpecEntity] = {
    'Comment': SpecEntity(
        name='Comment',
        fields=(
            SpecField(name='body', type='text', required=True, unique=False, default=None, max_length=None, min_value=None, max_value=None, enum_values=None),
            SpecField(name='post_id', type='uuid', required=True, unique=False),
        ),
    ),
    'Post': SpecEntity(
        name='Post',
        fields=(
            SpecField(name='title', type='string', required=True, unique=False, default=None, max_length=200, min_value=None, max_value=None, enum_values=None),
            SpecField(name='body', type='text', required=True, unique=False, default=None, max_length=None, min_value=None, max_value=None, enum_values=None),
            SpecField(name='published', type='boolean', required=True, unique=False, default=False, max_length=None, min_value=None, max_value=None, enum_values=None),
            SpecField(name='views', type='integer', required=False, unique=False, default=0, max_length=None, min_value=0.0, max_value=None, enum_values=None),
            SpecField(name='author_id', type='uuid', required=True, unique=False),
        ),
    ),
    'Tag': SpecEntity(
        name='Tag',
        fields=(
            SpecField(name='name', type='string', required=True, unique=True, default=None, max_length=50, min_value=None, max_value=None, enum_values=None),
        ),
    ),
    'User': SpecEntity(
        name='User',
        fields=(
            SpecField(name='email', type='string', required=True, unique=True, default=None, max_length=255, min_value=None, max_value=None, enum_values=None),
            SpecField(name='display_name', type='string', required=True, unique=False, default=None, max_length=100, min_value=None, max_value=None, enum_values=None),
            SpecField(name='role', type='enum', required=False, unique=False, default='member', max_length=None, min_value=None, max_value=None, enum_values=('admin', 'member')),
        ),
    ),
}
