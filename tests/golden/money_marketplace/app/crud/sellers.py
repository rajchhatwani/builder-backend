"""Repository for Seller (generated). Add custom queries by subclassing in your own module."""

from app.crud import _base as _crud_base
from app.models.sellers import Seller


class SellerRepository(_crud_base.Repository[Seller]):
    model = Seller
    soft_delete = False
    filterable = ()
    sortable = ()
    searchable = ()
    eager = ()
    references = {}
    many_to_many = {}
