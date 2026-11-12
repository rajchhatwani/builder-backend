"""Importing this package registers every table on `Base.metadata` (used by Alembic)."""

from app.auth import models as _auth_models
from app.models import _associations
from app.models._base import Base
from app.models.customers import Customer
from app.money.ledger import models as _ledger_models

__all__ = [
    "Base",
    "Customer",
    "_associations",
    "_auth_models",
    "_ledger_models",
]
