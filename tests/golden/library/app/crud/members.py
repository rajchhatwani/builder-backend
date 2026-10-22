"""Repository for Member (generated). Add custom queries by subclassing in your own module."""

from app.crud import _base as _crud_base
from app.models.books import Book
from app.models.members import Member


class MemberRepository(_crud_base.Repository[Member]):
    model = Member
    soft_delete = False
    filterable = ("email",)
    sortable = ()
    searchable = ()
    eager = ("borrowed_books", "profile", "sponsored")
    references = {"sponsor_id": Member}
    many_to_many = {"borrowed_books": Book}
