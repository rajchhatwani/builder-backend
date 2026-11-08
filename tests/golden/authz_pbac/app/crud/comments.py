"""Repository for Comment (generated). Add custom queries by subclassing in your own module."""

from app.crud import _base as _crud_base
from app.models.comments import Comment


class CommentRepository(_crud_base.Repository[Comment]):
    model = Comment
    soft_delete = False
    filterable = ()
    sortable = ()
    searchable = ()
    eager = ()
    references = {}
    many_to_many = {}
