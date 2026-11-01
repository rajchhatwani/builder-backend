"""Repository for Invoice (generated). Add custom queries by subclassing in your own module."""

from app.change_history.hooks import hooks_for as history_hooks_for
from app.change_history.hooks import merge_hooks
from app.crud import _base as _crud_base
from app.models.invoices import Invoice
from app.models.suppliers import Supplier
from app.state_machines.hooks import hooks_for as machine_hooks_for


class InvoiceRepository(_crud_base.Repository[Invoice]):
    model = Invoice
    soft_delete = False
    filterable = ("status",)
    sortable = ("created_at",)
    searchable = ()
    eager = ()
    references = {"supplier_id": Supplier}
    many_to_many = {}
    hooks = merge_hooks(machine_hooks_for("Invoice"), history_hooks_for("Invoice"))
