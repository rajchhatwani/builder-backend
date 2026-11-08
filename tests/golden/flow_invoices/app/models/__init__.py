"""Importing this package registers every table on `Base.metadata` (used by Alembic)."""

from app.auth import models as _auth_models
from app.models import _associations
from app.models._base import Base
from app.models.invoices import Invoice
from app.state_machines import models as _state_machine_models

__all__ = [
    "Base",
    "Invoice",
    "_associations",
    "_auth_models",
    "_state_machine_models",
]
