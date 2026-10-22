"""Repository for Comment (generated). Add custom queries by subclassing in your own module."""

from app.crud import _base as _crud_base
from app.models.comments import Comment
from app.models.posts import Post


class CommentRepository(_crud_base.Repository[Comment]):
    model = Comment
    soft_delete = False
    filterable = ()
    sortable = ()
    searchable = ()
    eager = ()
    references = {"post_id": Post}
    many_to_many = {}
