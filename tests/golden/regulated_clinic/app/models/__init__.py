"""Importing this package registers every table on `Base.metadata` (used by Alembic)."""

from app.auth import models as _auth_models
from app.compliance import models as _compliance_models
from app.models import _associations
from app.models._base import Base
from app.models.appointments import Appointment
from app.models.patients import Patient
from app.regulated import models as _regulated_models

__all__ = [
    "Base",
    "Appointment",
    "Patient",
    "_associations",
    "_auth_models",
    "_compliance_models",
    "_regulated_models",
]
