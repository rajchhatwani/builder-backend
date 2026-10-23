"""Repository for Blog (generated). Add custom queries by subclassing in your own module."""

from app.crud import _base as _crud_base
from app.models.blogs import Blog


class BlogRepository(_crud_base.Repository[Blog]):
    model = Blog
    soft_delete = False
    filterable = ()
    sortable = ()
    searchable = ()
    eager = ("articles",)
    references = {}
    many_to_many = {}
