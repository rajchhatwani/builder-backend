"""Repository for Invoice (generated). Add custom queries by subclassing in your own module."""

from app.crud import _base as _crud_base
from app.models.customers import Customer
from app.models.invoices import Invoice
from app.state_machines.hooks import hooks_for


class InvoiceRepository(_crud_base.Repository[Invoice]):
    model = Invoice
    soft_delete = False
    filterable = ("status",)
    sortable = ("created_at",)
    searchable = ()
    eager = ()
    references = {"customer_id": Customer}
    many_to_many = {}
    hooks = hooks_for("Invoice")
