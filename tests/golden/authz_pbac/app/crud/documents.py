"""Repository for Document (generated). Add custom queries by subclassing in your own module."""

from app.crud import _base as _crud_base
from app.models.documents import Document


class DocumentRepository(_crud_base.Repository[Document]):
    model = Document
    soft_delete = False
    filterable = ("status",)
    sortable = ()
    searchable = ()
    eager = ()
    references = {}
    many_to_many = {}
