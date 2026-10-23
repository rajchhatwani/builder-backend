"""Repository for GiftCard (generated). Add custom queries by subclassing in your own module."""

from app.crud import _base as _crud_base
from app.models.customers import Customer
from app.models.gift_cards import GiftCard


class GiftCardRepository(_crud_base.Repository[GiftCard]):
    model = GiftCard
    soft_delete = False
    filterable = ("code", "disabled")
    sortable = ()
    searchable = ()
    eager = ()
    references = {"customer_id": Customer}
    many_to_many = {}
