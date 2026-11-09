"""Repository for Expense (generated). Add custom queries by subclassing in your own module."""

from app.auth.field_access import HiddenFieldsMixin
from app.crud import _base as _crud_base
from app.models.expenses import Expense
from app.realtime import hooks as _realtime_hooks
from app.state_machines.hooks import hooks_for


class ExpenseRepository(HiddenFieldsMixin, _crud_base.Repository[Expense]):
    model = Expense
    soft_delete = True
    filterable = ("category",)
    sortable = ("category",)
    searchable = ()
    eager = ()
    references = {}
    many_to_many = {}
    hooks = hooks_for("Expense")


# The realtime event (ids only) is written in the same transaction, after the hooks above.
ExpenseRepository.hooks = _realtime_hooks.attach("Expense", ExpenseRepository.hooks)
