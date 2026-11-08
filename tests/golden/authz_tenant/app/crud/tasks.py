"""Repository for Task (generated). Add custom queries by subclassing in your own module."""

from app.crud import _base as _crud_base
from app.models.labels import Label
from app.models.tasks import Task


class TaskRepository(_crud_base.Repository[Task]):
    model = Task
    soft_delete = True
    filterable = ("done",)
    sortable = ()
    searchable = ()
    eager = ("labels",)
    references = {}
    many_to_many = {"labels": Label}
