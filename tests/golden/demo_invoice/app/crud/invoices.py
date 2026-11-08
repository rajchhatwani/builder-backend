"""Repository for Invoice (generated). Add custom queries by subclassing in your own module."""

import uuid as _uuid
from typing import Any

from app.change_history.hooks import hooks_for as history_hooks_for
from app.change_history.hooks import merge_hooks
from app.crud import _base as _crud_base
from app.models.invoices import Invoice
from app.models.suppliers import Supplier
from app.runtime_config import numbering as _numbering
from app.state_machines.hooks import hooks_for as machine_hooks_for


class InvoiceRepository(_crud_base.Repository[Invoice]):
    model = Invoice
    soft_delete = False
    filterable = ("status",)
    sortable = ("created_at",)
    searchable = ()
    eager = ()
    references = {"supplier_id": Supplier}
    many_to_many = {}
    hooks = merge_hooks(machine_hooks_for("Invoice"), history_hooks_for("Invoice"))
    # Fields numbered by a sequence: (field, sequence, per_tenant, as_int). Drawn inside the create's
    # transaction; never writable by a caller.
    numbered = (
        ('invoice_no', 'invoice_no', False, False),
    )

    async def create(self, data: dict[str, Any]) -> Invoice:
        data = dict(data)
        for field, sequence, per_tenant, as_int in self.numbered:
            data[field] = await _numbering.draw(
                self.session, sequence, tenant_id=self.tenant_id, per_tenant=per_tenant, as_int=as_int
            )
        return await super().create(data)

    async def _apply(self, item_id: _uuid.UUID, data: dict[str, Any]) -> Invoice:
        _numbering.refuse_change(tuple(n[0] for n in self.numbered), data)
        return await super()._apply(item_id, data)
