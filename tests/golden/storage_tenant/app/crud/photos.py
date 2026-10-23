"""Repository for Photo (generated). Add custom queries by subclassing in your own module."""

from app.crud import _base as _crud_base
from app.models.photos import Photo
from app.storage.refs import check_attachable


class PhotoRepository(_crud_base.Repository[Photo]):
    model = Photo
    soft_delete = False
    filterable = ()
    sortable = ()
    searchable = ()
    eager = ()
    references = {}
    many_to_many = {}
    file_fields = ("image_id", "thumbnail_id")
    file_check = staticmethod(check_attachable)
