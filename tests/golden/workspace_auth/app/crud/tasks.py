"""Repository for Task (generated). Add custom queries by subclassing in your own module."""

from app.crud import _base as _crud_base
from app.models.tasks import Task


class TaskRepository(_crud_base.Repository[Task]):
    model = Task
    soft_delete = False
    filterable = ()
    sortable = ()
    searchable = ()
    eager = ()
    references = {}
    many_to_many = {}
