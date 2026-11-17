"""Repository for Location (generated). Add custom queries by subclassing in your own module."""

from app.crud import _base as _crud_base
from app.models.locations import Location


class LocationRepository(_crud_base.Repository[Location]):
    model = Location
    soft_delete = False
    filterable = ("active",)
    sortable = ()
    searchable = ("name",)
    eager = ("fulfillments", "inventory_levels")
    references = {}
    many_to_many = {}
