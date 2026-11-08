"""Repository for User (generated). Add custom queries by subclassing in your own module."""

from app.crud import _base as _crud_base
from app.models.users import User


class UserRepository(_crud_base.Repository[User]):
    model = User
    soft_delete = False
    filterable = ("email",)
    sortable = ("email",)
    searchable = ()
    eager = ("posts",)
    references = {}
    many_to_many = {}
