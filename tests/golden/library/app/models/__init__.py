"""Importing this package registers every table on `Base.metadata` (used by Alembic)."""

from app.models import _associations
from app.models._base import Base
from app.models.authors import Author
from app.models.books import Book
from app.models.members import Member
from app.models.profiles import Profile
from app.models.shelves import Shelf

__all__ = [
    "Base",
    "Author",
    "Book",
    "Member",
    "Profile",
    "Shelf",
    "_associations",
]
