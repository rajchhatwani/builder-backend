"""Repository for Report (generated). Add custom queries by subclassing in your own module."""

from app.crud import _base as _crud_base
from app.models.reports import Report


class ReportRepository(_crud_base.Repository[Report]):
    model = Report
    soft_delete = False
    filterable = ()
    sortable = ()
    searchable = ()
    eager = ()
    references = {}
    many_to_many = {}
