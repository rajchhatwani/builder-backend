"""Repository for CustomerAddress (generated). Add custom queries by subclassing in your own module."""

from app.crud import _base as _crud_base
from app.models.customer_addresses import CustomerAddress
from app.models.customers import Customer


class CustomerAddressRepository(_crud_base.Repository[CustomerAddress]):
    model = CustomerAddress
    soft_delete = False
    filterable = ()
    sortable = ()
    searchable = ()
    eager = ()
    references = {"customer_id": Customer}
    many_to_many = {}
