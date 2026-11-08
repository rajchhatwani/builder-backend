"""Repository for LeaveRequest (generated). Add custom queries by subclassing in your own module."""

from app.crud import _base as _crud_base
from app.models.leave_requests import LeaveRequest
from app.state_machines.hooks import hooks_for


class LeaveRequestRepository(_crud_base.Repository[LeaveRequest]):
    model = LeaveRequest
    soft_delete = False
    filterable = ("state",)
    sortable = ("created_at",)
    searchable = ()
    eager = ()
    references = {}
    many_to_many = {}
    hooks = hooks_for("LeaveRequest")
