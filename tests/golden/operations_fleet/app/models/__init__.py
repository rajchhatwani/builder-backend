"""Importing this package registers every table on `Base.metadata` (used by Alembic)."""

from app.auth import models as _auth_models
from app.models import _associations
from app.models._base import Base
from app.models.vehicles import Vehicle
from app.operations.geo import models as _geo_models
from app.operations.location import models as _location_models
from app.operations.matching import models as _matching_models
from app.operations.prediction import models as _prediction_models

__all__ = [
    "Base",
    "Vehicle",
    "_associations",
    "_auth_models",
    "_geo_models",
    "_location_models",
    "_matching_models",
    "_prediction_models",
]
