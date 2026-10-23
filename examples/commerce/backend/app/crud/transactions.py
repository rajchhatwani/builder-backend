"""Repository for Transaction (generated). Add custom queries by subclassing in your own module."""

from app.crud import _base as _crud_base
from app.models.orders import Order
from app.models.transactions import Transaction


class TransactionRepository(_crud_base.Repository[Transaction]):
    model = Transaction
    soft_delete = False
    filterable = ()
    sortable = ()
    searchable = ()
    eager = ()
    references = {"order_id": Order}
    many_to_many = {}
