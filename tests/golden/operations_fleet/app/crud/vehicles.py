"""Repository for Vehicle (generated). Add custom queries by subclassing in your own module."""

from app.crud import _base as _crud_base
from app.models.vehicles import Vehicle


class VehicleRepository(_crud_base.Repository[Vehicle]):
    model = Vehicle
    soft_delete = False
    filterable = ()
    sortable = ()
    searchable = ()
    eager = ()
    references = {}
    many_to_many = {}
