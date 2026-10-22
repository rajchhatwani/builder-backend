"""Repository for Profile (generated). Add custom queries by subclassing in your own module."""

from app.crud import _base as _crud_base
from app.models.members import Member
from app.models.profiles import Profile


class ProfileRepository(_crud_base.Repository[Profile]):
    model = Profile
    soft_delete = False
    filterable = ()
    sortable = ()
    searchable = ()
    eager = ()
    references = {"member_id": Member}
    many_to_many = {}
