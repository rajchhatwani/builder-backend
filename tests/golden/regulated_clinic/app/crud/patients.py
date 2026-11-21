"""Repository for Patient (generated). Add custom queries by subclassing in your own module."""

from app.crud import _base as _crud_base
from app.models.patients import Patient


class PatientRepository(_crud_base.Repository[Patient]):
    model = Patient
    soft_delete = False
    filterable = ("postcode",)
    sortable = ("created_at",)
    searchable = ()
    eager = ("appointments",)
    references = {}
    many_to_many = {}
