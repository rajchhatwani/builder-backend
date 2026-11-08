"""Importing this package registers every table on `Base.metadata` (used by Alembic)."""

from app.jobs import models as _job_models
from app.models import _associations
from app.models._base import Base
from app.models.invoices import Invoice

__all__ = [
    "Base",
    "Invoice",
    "_associations",
    "_job_models",
]
