"""Repository for Book (generated). Add custom queries by subclassing in your own module."""

from app.crud import _base as _crud_base
from app.models.authors import Author
from app.models.books import Book
from app.models.members import Member
from app.models.shelves import Shelf


class BookRepository(_crud_base.Repository[Book]):
    model = Book
    soft_delete = True
    filterable = ("in_stock", "pages", "status")
    sortable = ("pages", "published_at", "title")
    searchable = ("isbn", "title")
    eager = ("borrowers",)
    references = {"author_id": Author, "shelf_id": Shelf}
    many_to_many = {"borrowers": Member}
