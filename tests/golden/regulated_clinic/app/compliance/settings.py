"""Compliance settings (generated from the spec: change them in the builder). Plain data, no secret."""

from typing import Any

# Roles that administer legal holds, retention runs, consent and exports. Nobody else gets in (default deny).
ROLES: tuple[str, ...] = ('admin', 'compliance_officer')

# entity -> where its model lives
ENTITIES: dict[str, dict[str, str]] = {'Appointment': {'class': 'Appointment',
                 'module': 'app.models.appointments',
                 'table': 'appointments'},
 'Patient': {'class': 'Patient', 'module': 'app.models.patients', 'table': 'patients'}}

# retention rules: entity, days, date_field, action (purge | anonymise), anonymise_fields
RETENTION: list[dict[str, Any]] = [{'action': 'anonymise',
  'anonymise_fields': ('phone', 'notes', 'insurance_no'),
  'date_field': 'created_at',
  'days': 3650,
  'entity': 'Patient'},
 {'action': 'purge',
  'anonymise_fields': (),
  'date_field': 'scheduled_at',
  'days': 730,
  'entity': 'Appointment'},
 {'action': 'purge',
  'anonymise_fields': (),
  'date_field': 'created_at',
  'days': 7300,
  'entity': 'Patient'}]

CONSENT_PURPOSES: tuple[str, ...] = ('treatment', 'research')

BREAK_GLASS: dict[str, Any] = {'enabled': True, 'max_minutes': 60, 'roles': ('clinician_lead',)}

# export: entity -> {"subject_field": field whose value is the consent subject}; field -> keep | drop | hash | generalise
EXPORT_ENTITIES: dict[str, dict[str, Any]] = {'Patient': {'subject_field': 'id'}}
EXPORT_FIELDS: dict[str, dict[str, str]] = {'Patient': {'age': 'generalise',
             'created_at': 'generalise',
             'dob': 'drop',
             'name': 'hash',
             'notes': 'drop',
             'phone': 'drop',
             'postcode': 'generalise'}}
EXPORT_CONSENT_PURPOSE: str | None = 'research'

# multi-tenant project: holds, grants, audit rows and reads belong to the caller's tenant; a user without one is refused
TENANT_SCOPED: bool = True

# fields regulated mode protects, per entity: an export may only hash or drop them
PROTECTED: dict[str, tuple[str, ...]] = {'Patient': ('dob', 'insurance_no', 'name', 'phone')}
