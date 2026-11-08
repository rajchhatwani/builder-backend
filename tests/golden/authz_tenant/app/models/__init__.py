"""Importing this package registers every table on `Base.metadata` (used by Alembic)."""

from app.auth import models as _auth_models
from app.models import _associations
from app.models._base import Base
from app.models.labels import Label
from app.models.tasks import Task

__all__ = [
    "Base",
    "Label",
    "Task",
    "_associations",
    "_auth_models",
]
