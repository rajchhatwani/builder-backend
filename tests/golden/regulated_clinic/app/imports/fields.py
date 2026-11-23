"""Importable fields per entity (generated from the spec): the columns a CSV may fill, with their limits."""

from app.imports.csv_import import SpecEntity, SpecField

ENTITIES: dict[str, SpecEntity] = {
    'Appointment': SpecEntity(
        name='Appointment',
        fields=(
            SpecField(name='scheduled_at', type='datetime', required=True, unique=False, default=None, max_length=None, min_value=None, max_value=None, enum_values=None),
            SpecField(name='reason', type='string', required=False, unique=False, default=None, max_length=200, min_value=None, max_value=None, enum_values=None),
            SpecField(name='status', type='enum', required=True, unique=False, default=None, max_length=None, min_value=None, max_value=None, enum_values=('booked', 'done', 'cancelled')),
            SpecField(name='patient_id', type='uuid', required=False, unique=False),
        ),
    ),
    'Patient': SpecEntity(
        name='Patient',
        fields=(
            SpecField(name='name', type='string', required=True, unique=False, default=None, max_length=120, min_value=None, max_value=None, enum_values=None),
            SpecField(name='dob', type='string', required=False, unique=False, default=None, max_length=20, min_value=None, max_value=None, enum_values=None),
            SpecField(name='phone', type='string', required=False, unique=False, default=None, max_length=30, min_value=None, max_value=None, enum_values=None),
            SpecField(name='postcode', type='string', required=False, unique=False, default=None, max_length=10, min_value=None, max_value=None, enum_values=None),
            SpecField(name='age', type='integer', required=False, unique=False, default=None, max_length=None, min_value=None, max_value=None, enum_values=None),
            SpecField(name='notes', type='text', required=False, unique=False, default=None, max_length=None, min_value=None, max_value=None, enum_values=None),
            SpecField(name='insurance_no', type='string', required=False, unique=False, default=None, max_length=40, min_value=None, max_value=None, enum_values=None),
        ),
    ),
}
