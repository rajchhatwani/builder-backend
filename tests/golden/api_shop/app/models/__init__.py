"""Importing this package registers every table on `Base.metadata` (used by Alembic)."""

from app.auth import models as _auth_models
from app.models import _associations
from app.models._base import Base
from app.models.products import Product
from app.models.reviews import Review
from app.platform_api import models as _platform_api_models

__all__ = [
    "Base",
    "Product",
    "Review",
    "_associations",
    "_auth_models",
    "_platform_api_models",
]
