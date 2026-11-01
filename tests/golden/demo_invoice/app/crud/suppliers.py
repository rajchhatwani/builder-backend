"""Repository for Supplier (generated). Add custom queries by subclassing in your own module."""

from app.change_history.hooks import hooks_for
from app.crud import _base as _crud_base
from app.models.suppliers import Supplier


class SupplierRepository(_crud_base.Repository[Supplier]):
    model = Supplier
    soft_delete = False
    filterable = ("active",)
    sortable = ("name",)
    searchable = ()
    eager = ("invoices",)
    references = {}
    many_to_many = {}
    hooks = hooks_for("Supplier")
