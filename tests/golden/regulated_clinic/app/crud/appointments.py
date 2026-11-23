"""Repository for Appointment (generated). Add custom queries by subclassing in your own module."""

from app.crud import _base as _crud_base
from app.models.appointments import Appointment
from app.models.patients import Patient


class AppointmentRepository(_crud_base.Repository[Appointment]):
    model = Appointment
    soft_delete = False
    filterable = ("status",)
    sortable = ("scheduled_at",)
    searchable = ()
    eager = ()
    references = {"patient_id": Patient}
    many_to_many = {}
