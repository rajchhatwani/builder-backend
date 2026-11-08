"""Repository for Customer (generated). Add custom queries by subclassing in your own module."""

from app.crud import _base as _crud_base
from app.models.customers import Customer


class CustomerRepository(_crud_base.Repository[Customer]):
    model = Customer
    soft_delete = False
    filterable = ("active",)
    sortable = ("name",)
    searchable = ()
    eager = ("invoices",)
    references = {}
    many_to_many = {}
