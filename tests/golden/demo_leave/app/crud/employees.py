"""Repository for Employee (generated). Add custom queries by subclassing in your own module."""

from app.change_history.hooks import hooks_for
from app.crud import _base as _crud_base
from app.models.employees import Employee


class EmployeeRepository(_crud_base.Repository[Employee]):
    model = Employee
    soft_delete = False
    filterable = ("department",)
    sortable = ("name",)
    searchable = ()
    eager = ("leave_requests",)
    references = {}
    many_to_many = {}
    hooks = hooks_for("Employee")
