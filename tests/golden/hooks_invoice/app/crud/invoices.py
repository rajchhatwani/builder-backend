"""Repository for Invoice (generated). Add custom queries by subclassing in your own module."""

from app.crud import _base as _crud_base
from app.hooks_gen import registry as custom_hooks
from app.models.invoices import Invoice
from app.state_machines.hooks import hooks_for


class InvoiceRepository(_crud_base.Repository[Invoice]):
    model = Invoice
    soft_delete = False
    filterable = ("status",)
    sortable = ("created_at",)
    searchable = ()
    eager = ()
    references = {}
    many_to_many = {}
    hooks = custom_hooks.merge_hooks(
        hooks_for("Invoice"),
        custom_hooks.hooks_for("Invoice"),
    )
