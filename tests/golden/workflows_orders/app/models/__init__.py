"""Importing this package registers every table on `Base.metadata` (used by Alembic)."""

from app.auth import models as _auth_models
from app.jobs import models as _job_models
from app.models import _associations
from app.models._base import Base
from app.models.customers import Customer
from app.models.orders import Order
from app.workflows import models as _workflow_models

__all__ = [
    "Base",
    "Customer",
    "Order",
    "_associations",
    "_auth_models",
    "_workflow_models",
    "_job_models",
]
