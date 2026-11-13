"""Importing this package registers every table on `Base.metadata` (used by Alembic)."""

from app.ai import documents_models as _ai_documents_models
from app.ai import knowledge_models as _ai_knowledge_models
from app.ai import models as _ai_models
from app.auth import models as _auth_models
from app.models import _associations
from app.models._base import Base
from app.models.tickets import Ticket

__all__ = [
    "Base",
    "Ticket",
    "_associations",
    "_auth_models",
    "_ai_models",
    "_ai_documents_models",
    "_ai_knowledge_models",
]
