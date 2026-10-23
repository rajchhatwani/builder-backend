"""Repository for TaxRate (generated). Add custom queries by subclassing in your own module."""

from app.crud import _base as _crud_base
from app.models.tax_rates import TaxRate


class TaxRateRepository(_crud_base.Repository[TaxRate]):
    model = TaxRate
    soft_delete = False
    filterable = ()
    sortable = ()
    searchable = ()
    eager = ()
    references = {}
    many_to_many = {}
