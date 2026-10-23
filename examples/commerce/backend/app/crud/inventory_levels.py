"""Repository for InventoryLevel (generated). Add custom queries by subclassing in your own module."""

from app.crud import _base as _crud_base
from app.models.inventory_levels import InventoryLevel
from app.models.locations import Location
from app.models.variants import Variant


class InventoryLevelRepository(_crud_base.Repository[InventoryLevel]):
    model = InventoryLevel
    soft_delete = False
    filterable = ("available",)
    sortable = ("available", "updated_at")
    searchable = ()
    eager = ()
    references = {"location_id": Location, "variant_id": Variant}
    many_to_many = {}
