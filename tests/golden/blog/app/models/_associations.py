"""Join tables for many_to_many relations (generated)."""
import sqlalchemy as _sa

from app.models import _base as _models_base

_sa.Table(
    "posts_tags",
    _models_base.Base.metadata,
    _sa.Column(
        "left_id",
        _sa.Uuid(),
        _sa.ForeignKey("posts.id", ondelete="RESTRICT"),
        primary_key=True,
    ),
    _sa.Column(
        "right_id",
        _sa.Uuid(),
        _sa.ForeignKey("tags.id", ondelete="RESTRICT"),
        primary_key=True,
    ),
)
