"""Repository for Note (generated). Add custom queries by subclassing in your own module."""

from app.change_history.hooks import hooks_for
from app.crud import _base as _crud_base
from app.models.notes import Note


class NoteRepository(_crud_base.Repository[Note]):
    model = Note
    soft_delete = False
    filterable = ("title",)
    sortable = ("created_at",)
    searchable = ()
    eager = ()
    references = {}
    many_to_many = {}
    hooks = hooks_for("Note")
