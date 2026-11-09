"""Repository for Employee (generated). Add custom queries by subclassing in your own module."""

from app.auth.field_access import HiddenFieldsMixin
from app.crud import _base as _crud_base
from app.models.employees import Employee
from app.search import hooks as _search_hooks
from app.state_machines.hooks import hooks_for


class EmployeeRepository(HiddenFieldsMixin, _crud_base.Repository[Employee]):
    model = Employee
    soft_delete = False
    filterable = ("name", "salary")
    sortable = ("name", "salary")
    searchable = ("name", "notes")
    eager = ()
    references = {}
    many_to_many = {}
    hooks = hooks_for("Employee")


# Keeps the external search index in step (no-op with SEARCH_BACKEND=fts).
EmployeeRepository.hooks = _search_hooks.attach(
    "Employee", ("name", "notes"), EmployeeRepository.hooks
)
