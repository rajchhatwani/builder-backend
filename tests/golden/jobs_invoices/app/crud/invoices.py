"""Repository for Invoice (generated). Add custom queries by subclassing in your own module."""

from app.crud import _base as _crud_base
from app.models.invoices import Invoice


class InvoiceRepository(_crud_base.Repository[Invoice]):
    model = Invoice
    soft_delete = False
    filterable = ()
    sortable = ("created_at",)
    searchable = ()
    eager = ()
    references = {}
    many_to_many = {}
