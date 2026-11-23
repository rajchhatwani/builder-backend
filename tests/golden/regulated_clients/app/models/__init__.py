"""Importing this package registers every table on `Base.metadata` (used by Alembic)."""

from app.auth import models as _auth_models
from app.change_history import models as _change_history_models
from app.events import models as _event_models
from app.jobs import models as _job_models
from app.models import _associations
from app.models._base import Base
from app.models.customers import Customer
from app.models.orders import Order
from app.providers import models as _provider_models
from app.regulated import models as _regulated_models
from app.webhooks import models as _webhook_models

__all__ = [
    "Base",
    "Customer",
    "Order",
    "_associations",
    "_auth_models",
    "_change_history_models",
    "_event_models",
    "_provider_models",
    "_job_models",
    "_webhook_models",
    "_regulated_models",
]
