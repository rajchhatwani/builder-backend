"""Repository for Metafield (generated). Add custom queries by subclassing in your own module."""

from app.crud import _base as _crud_base
from app.models.metafields import Metafield


class MetafieldRepository(_crud_base.Repository[Metafield]):
    model = Metafield
    soft_delete = False
    filterable = ("key", "namespace", "owner_id", "owner_type")
    sortable = ()
    searchable = ()
    eager = ()
    references = {}
    many_to_many = {}
