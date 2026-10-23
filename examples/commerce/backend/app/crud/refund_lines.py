"""Repository for RefundLine (generated). Add custom queries by subclassing in your own module."""

from app.crud import _base as _crud_base
from app.models.order_lines import OrderLine
from app.models.refund_lines import RefundLine
from app.models.refunds import Refund


class RefundLineRepository(_crud_base.Repository[RefundLine]):
    model = RefundLine
    soft_delete = False
    filterable = ()
    sortable = ()
    searchable = ()
    eager = ()
    references = {"order_line_id": OrderLine, "refund_id": Refund}
    many_to_many = {}
