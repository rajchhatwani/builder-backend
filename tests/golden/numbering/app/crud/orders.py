"""Repository for Order (generated). Add custom queries by subclassing in your own module."""

import uuid as _uuid
from typing import Any

from app.crud import _base as _crud_base
from app.models.orders import Order
from app.runtime_config import numbering as _numbering
from app.state_machines.hooks import hooks_for


class OrderRepository(_crud_base.Repository[Order]):
    model = Order
    soft_delete = False
    filterable = ("stage",)
    sortable = ("created_at",)
    searchable = ()
    eager = ()
    references = {}
    many_to_many = {}
    hooks = hooks_for("Order")
    # Fields numbered by a sequence: (field, sequence, per_tenant, as_int). Drawn inside the create's
    # transaction; never writable by a caller.
    numbered = (
        ('invoice_no', 'invoice_no', False, False),
        ('order_no', 'order_no', False, False),
        ('ticket_no', 'ticket_no', False, True),
    )

    async def create(self, data: dict[str, Any]) -> Order:
        data = dict(data)
        for field, sequence, per_tenant, as_int in self.numbered:
            data[field] = await _numbering.draw(
                self.session, sequence, tenant_id=self.tenant_id, per_tenant=per_tenant, as_int=as_int
            )
        return await super().create(data)

    async def _apply(self, item_id: _uuid.UUID, data: dict[str, Any]) -> Order:
        _numbering.refuse_change(tuple(n[0] for n in self.numbered), data)
        return await super()._apply(item_id, data)
