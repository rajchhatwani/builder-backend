"""Repository for LeaveRequest (generated). Add custom queries by subclassing in your own module."""

from app.change_history.hooks import hooks_for as history_hooks_for
from app.crud import _base as _crud_base
from app.hooks_gen import registry as custom_hooks
from app.models.employees import Employee
from app.models.leave_requests import LeaveRequest
from app.state_machines.hooks import hooks_for as machine_hooks_for


class LeaveRequestRepository(_crud_base.Repository[LeaveRequest]):
    model = LeaveRequest
    soft_delete = False
    filterable = ("state",)
    sortable = ("created_at",)
    searchable = ()
    eager = ()
    references = {"employee_id": Employee}
    many_to_many = {}
    hooks = custom_hooks.merge_hooks(
        machine_hooks_for("LeaveRequest"),
        history_hooks_for("LeaveRequest"),
        custom_hooks.hooks_for("LeaveRequest"),
    )
