"""Repository for Note (generated). Add custom queries by subclassing in your own module."""

from app.crud import _base as _crud_base
from app.hooks_gen import registry as custom_hooks
from app.models.notes import Note


class NoteRepository(_crud_base.Repository[Note]):
    model = Note
    soft_delete = False
    filterable = ()
    sortable = ()
    searchable = ()
    eager = ()
    references = {}
    many_to_many = {}
    hooks = custom_hooks.merge_hooks(
        custom_hooks.hooks_for("Note"),
    )
