"""Repository for LeaveRequest (generated). Add custom queries by subclassing in your own module."""

import uuid as _uuid
from typing import Any

from app.change_history.hooks import hooks_for as history_hooks_for
from app.crud import _base as _crud_base
from app.hooks_gen import registry as custom_hooks
from app.models.employees import Employee
from app.models.leave_requests import LeaveRequest
from app.runtime_config import numbering as _numbering
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
    # Fields numbered by a sequence: (field, sequence, per_tenant, as_int). Drawn inside the create's
    # transaction; never writable by a caller.
    numbered = (
        ('request_no', 'request_no', False, False),
    )

    async def create(self, data: dict[str, Any]) -> LeaveRequest:
        data = dict(data)
        for field, sequence, per_tenant, as_int in self.numbered:
            data[field] = await _numbering.draw(
                self.session, sequence, tenant_id=self.tenant_id, per_tenant=per_tenant, as_int=as_int
            )
        return await super().create(data)

    async def _apply(self, item_id: _uuid.UUID, data: dict[str, Any]) -> LeaveRequest:
        _numbering.refuse_change(tuple(n[0] for n in self.numbered), data)
        return await super()._apply(item_id, data)
