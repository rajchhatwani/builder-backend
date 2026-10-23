"""Repository for Announcement (generated). Add custom queries by subclassing in your own module."""

from app.crud import _base as _crud_base
from app.models.announcements import Announcement


class AnnouncementRepository(_crud_base.Repository[Announcement]):
    model = Announcement
    soft_delete = False
    filterable = ()
    sortable = ()
    searchable = ()
    eager = ("tasks",)
    references = {}
    many_to_many = {}
