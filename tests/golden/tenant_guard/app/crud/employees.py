"""Repository for Employee (generated). Add custom queries by subclassing in your own module."""

from app.auth.field_access import HiddenFieldsMixin
from app.change_history.hooks import hooks_for as history_hooks_for
from app.change_history.hooks import merge_hooks
from app.crud import _base as _crud_base
from app.models.employees import Employee
from app.realtime import hooks as _realtime_hooks
from app.search import hooks as _search_hooks
from app.state_machines.hooks import hooks_for as machine_hooks_for


class EmployeeRepository(HiddenFieldsMixin, _crud_base.Repository[Employee]):
    model = Employee
    soft_delete = False
    filterable = ("name", "salary")
    sortable = ("name", "salary")
    searchable = ("name", "notes")
    eager = ()
    references = {}
    many_to_many = {}
    hooks = merge_hooks(machine_hooks_for("Employee"), history_hooks_for("Employee"))


# Keeps the external search index in step (no-op with SEARCH_BACKEND=fts).
EmployeeRepository.hooks = _search_hooks.attach(
    "Employee", ("name", "notes"), EmployeeRepository.hooks
)


# The realtime event (ids only) is written in the same transaction, after the hooks above.
EmployeeRepository.hooks = _realtime_hooks.attach("Employee", EmployeeRepository.hooks)
