"""Repository for Payroll (generated). Add custom queries by subclassing in your own module."""

from app.crud import _base as _crud_base
from app.models.payrolls import Payroll
from app.realtime import hooks as _realtime_hooks


class PayrollRepository(_crud_base.Repository[Payroll]):
    model = Payroll
    soft_delete = False
    filterable = ()
    sortable = ()
    searchable = ()
    eager = ()
    references = {}
    many_to_many = {}


# The realtime event (ids only) is written in the same transaction, after the hooks above.
PayrollRepository.hooks = _realtime_hooks.attach("Payroll", PayrollRepository.hooks)
