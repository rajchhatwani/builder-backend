"""Importing this package registers every table on `Base.metadata` (used by Alembic)."""

from app.auth import models as _auth_models
from app.models import _associations
from app.models._base import Base
from app.models.sellers import Seller
from app.money.invoicing import models as _invoicing_models
from app.money.ledger import models as _ledger_models
from app.money.reconciliation import models as _reconciliation_models

__all__ = [
    "Base",
    "Seller",
    "_associations",
    "_auth_models",
    "_ledger_models",
    "_reconciliation_models",
    "_invoicing_models",
]
