"""Repository for Label (generated). Add custom queries by subclassing in your own module."""

from app.crud import _base as _crud_base
from app.models.labels import Label
from app.models.tasks import Task


class LabelRepository(_crud_base.Repository[Label]):
    model = Label
    soft_delete = False
    filterable = ()
    sortable = ()
    searchable = ()
    eager = ("tasks",)
    references = {}
    many_to_many = {"tasks": Task}
