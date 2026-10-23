"""Repository for CartLine (generated). Add custom queries by subclassing in your own module."""

from app.crud import _base as _crud_base
from app.models.cart_lines import CartLine
from app.models.carts import Cart
from app.models.variants import Variant


class CartLineRepository(_crud_base.Repository[CartLine]):
    model = CartLine
    soft_delete = False
    filterable = ()
    sortable = ()
    searchable = ()
    eager = ()
    references = {"cart_id": Cart, "variant_id": Variant}
    many_to_many = {}
