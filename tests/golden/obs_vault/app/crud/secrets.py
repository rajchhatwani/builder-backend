"""Repository for Secret (generated). Add custom queries by subclassing in your own module."""

from app.crud import _base as _crud_base
from app.models.secrets import Secret


class SecretRepository(_crud_base.Repository[Secret]):
    model = Secret
    soft_delete = False
    filterable = ()
    sortable = ()
    searchable = ()
    eager = ()
    references = {}
    many_to_many = {}
